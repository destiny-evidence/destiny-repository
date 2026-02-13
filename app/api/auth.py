"""
Tools for authorising requests.

Authentication assistance methods.

This module is based on the following references :

- https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#validate-tokens
- https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation
- https://github.com/Azure-Samples/ms-identity-python-webapi-azurefunctions/blob/master/Function/secureFlaskApp/__init__.py
- https://github.com/425show/fastapi_microsoft_identity/blob/main/fastapi_microsoft_identity/auth_service.py
"""

import hmac
from collections.abc import Awaitable, Callable
from enum import StrEnum, auto
from typing import Annotated, Any, Protocol
from uuid import UUID

import destiny_sdk
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose import errors as jose_errors
from cachetools import TTLCache
from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import AsyncClient
from jose import exceptions, jwt
from opentelemetry import trace

from app.core.config import get_settings
from app.core.exceptions import AuthError, NotFoundError
from app.core.telemetry.attributes import Attributes

CACHE_TTL = 60 * 60 * 24  # 24 hours

settings = get_settings()

# Dependency to get the token from the Authorization header
# `auto_error=False` allows us to provide a more meaningful error message
# when the token is missing.
# Also allows the ignoring bearer tokens when during testing
# or in development environments
security = HTTPBearer(auto_error=False)


class AuthRole(StrEnum):
    """Enum describing the available app roles that can be granted to applications."""

    ADMINISTRATOR = "administrator"
    IMPORT_WRITER = "import.writer"
    REFERENCE_READER = "reference.reader"
    REFERENCE_DEDUPLICATOR = "reference.deduplicator"
    ENHANCEMENT_REQUEST_WRITER = "enhancement_request.writer"


class AuthScope(StrEnum):
    """Enum describing the available auth scopes can be granted to users."""

    ADMINISTRATOR = "administrator.all"
    IMPORT_WRITER = "import.writer.all"
    REFERENCE_READER = "reference.reader.all"
    REFERENCE_DEDUPLICATOR = "reference.deduplicator.all"
    ENHANCEMENT_REQUEST_WRITER = "enhancement_request.writer.all"
    ROBOT_WRITER = "robot.writer.all"


class HMACClientType(StrEnum):
    """
    Enum describing the type of HMAC client.

    This is only used for telemetry purposes.
    """

    ROBOT = auto()


class AuthMethod(Protocol):
    """

    Protocol for auth methods, enforcing the implementation of __call__().

    Inherit from this class when adding an auth implementation.

    This allows FastAPI to call class instances as dependencies in FastAPI routes,
    see https://fastapi.tiangolo.com/advanced/advanced-dependencies

        .. code-block:: python

            auth = AuthMethod()

            router = APIRouter(
                prefix="/imports", tags=["imports"], dependencies=[Depends(auth)]
            )

    """

    async def __call__(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None,
    ) -> bool:
        """
        Callable interface to allow use as a dependency.

        :param credentials: The bearer token provided in the request (as a dependency)
        :type credentials: HTTPAuthorizationCredentials | None
        :raises NotImplementedError: __call__() method has not been implemented.
        :return: True if authorization is successful.
        :rtype: bool
        """
        raise NotImplementedError


class StrategyAuth(AuthMethod):
    """
    A meta-auth method which chooses the auth method at runtime.

    Calls the auth strategy selector every time the dependency is invoked.

        .. code-block:: python

            def auth_strategy():
                return AzureJwtAuth(
                    application_id=settings.application_id,
                    scope=AuthScopes.READ,
                )

            strategy_auth = StrategyAuth(selector=auth_strategy)

            router = APIRouter(
                prefix="/imports",
                tags=["imports"],
                dependencies=[Depends(strategy_auth)]
            )

    """

    _selector: Callable[[], AuthMethod]

    def __init__(
        self,
        selector: Callable[[], AuthMethod],
    ) -> None:
        """
        Initialise strategy.

        :param selector: A callable which returns the AuthMethod to be used.
        :type selector: Callable[[], AuthMethod]

        """
        self._selector = selector

    def _get_strategy(self) -> AuthMethod:
        return self._selector()

    async def __call__(
        self,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> bool:
        """Callable interface to allow use as a dependency."""
        return await self._get_strategy()(request=request, credentials=credentials)


class CachingStrategyAuth(StrategyAuth):
    """
    A subclass of StrategyAuth which caches the selected strategy across calls.

    .. code-block:: python

            def auth_strategy():
                return AzureJwtAuth(
                    application_id=settings.application_id,
                    scope=AuthScopes.READ,
                )

            caching_auth = CachingStrategyAuth(selector=auth_strategy)

            router = APIRouter(
                prefix="/imports",
                tags=["imports"],
                dependencies=[Depends(caching_auth)]
            )

    """

    _cached_strategy: AuthMethod | None

    def __init__(self, selector: Callable[[], AuthMethod]) -> None:
        """
        Initialise strategy.

        :param selector: A callable which returns the AuthMethod to be used.
        :type selector: Callable[[], AuthMethod]

        """
        super().__init__(selector)
        self._cached_strategy = None

    def _get_strategy(self) -> AuthMethod:
        if self._cached_strategy:
            return self._cached_strategy
        self._cached_strategy = super()._get_strategy()
        return self._cached_strategy

    def reset(self) -> None:
        """Reset the cached strategy so it is fetched at next call."""
        self._cached_strategy = None


class AzureJwtAuth(AuthMethod):
    """
    AuthMethod for authorizing requests using the JWT provided by Azure.

    When using AzureJwtAuth implement your auth scopes as a StrEnum

    To use AzureJwtAuth you will need to have an Entra Id application registration
    with app roles configured for your auth scopes.

    Any client communicating with your service requires assignment to the app role
    that matches the auth scope it wishes to use. Azure will provide these scopes
    back in the JWT.

        .. code-block:: python

            class AuthScopes(StrEnum):
                READ = "read"

            def auth_strategy():
                return AzureJwtAuth(
                    application_id=settings.application_id,
                    scope=AuthScopes.READ,
                )

            caching_auth = CachingStrategyAuth(selector=auth_strategy)

            router = APIRouter(
                prefix="/imports",
                tags=["imports"],
                dependencies=[Depends(caching_auth)]
            )

    """

    def __init__(
        self,
        application_id: str,
        scope: StrEnum | None = None,
        role: StrEnum | None = None,
        cache_ttl: int = CACHE_TTL,
    ) -> None:
        """
        Initialize the dependency.

        Args:
        application_id (str): The Azure AD application ID
        scope (AuthScopes): The authorization scope for delegated (user) tokens
        role (AuthRoles): The authorization role for application tokens
        cache_ttl (int): Time to live for cache entries, defaults to 24 hours.

        """
        self.api_audience = application_id
        self.scope = scope
        self.role = role
        self.login_url = settings.azure_login_url.rstrip("/")
        self.cache: TTLCache = TTLCache(maxsize=1, ttl=cache_ttl)

    async def verify_token(self, token: str) -> dict[str, Any]:
        """
        Verify the token using the JWKS fetched from the Microsoft Entra endpoint.

        Args:
        token (str): The JWT to be verified

        """
        try:
            jwks = self.cache.get("jwks")
            cached_jwks = bool(jwks)
            if not jwks:
                jwks = await self._get_microsoft_keys()
                self.cache["jwks"] = jwks

            unverified_header = jwt.get_unverified_header(token)
            rsa_key = {}
            for key in jwks["keys"]:
                if key["kid"] == unverified_header["kid"]:
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"],
                    }
        except Exception as exc:
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to parse authentication token.",
            ) from exc

        if rsa_key:
            try:
                expected_issuer = f"{self.login_url}/v2.0"
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=["RS256"],
                    audience=self.api_audience,
                    issuer=expected_issuer,
                )
            except exceptions.ExpiredSignatureError as exc:
                raise AuthError(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is expired."
                ) from exc
            except exceptions.JWTClaimsError as exc:
                unverified = jwt.get_unverified_claims(token)
                token_aud = unverified.get("aud")
                token_iss = unverified.get("iss")
                raise AuthError(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"Incorrect claims. "
                        f"Expected aud={self.api_audience}, got={token_aud}. "
                        f"Expected iss={expected_issuer}, got={token_iss}"
                    ),
                ) from exc
            except Exception as exc:
                if cached_jwks:
                    self.cache.pop("jwks", None)
                    return await self.verify_token(token)
                raise AuthError(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unable to parse authentication token.",
                ) from exc
            else:
                return payload
        raise AuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find appropriate key.",
        )

    async def _get_microsoft_keys(self) -> Any:  # noqa: ANN401
        async with AsyncClient() as client:
            response = await client.get(f"{self.login_url}/discovery/v2.0/keys")
            return response.json()

    def _require_scope_or_role(self, verified_claims: dict[str, Any]) -> bool:
        # Delegated (user) token: check scopes
        if self.scope and verified_claims.get("scp"):
            scopes = verified_claims["scp"].split()
            if self.scope.value in scopes:
                return True

            raise AuthError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"IDW10203: The scope permissions (scp) claim does not contain the required scope {self.scope.value}",  # noqa: E501
            )

        # Application token: check roles
        if self.role and verified_claims.get("roles"):
            roles = verified_claims["roles"]
            if self.role.value in roles:
                return True

            raise AuthError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"IDW10203: The role permissions (roles) claim does not contain the required role {self.role.value}",  # noqa: E501
            )

        raise AuthError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IDW10201: Neither scope or roles claim was found in the bearer token.",  # noqa: E501
        )

    async def __call__(
        self,
        request: Request,  # noqa: ARG002
        credentials: HTTPAuthorizationCredentials | None,
    ) -> bool:
        """Authenticate the request."""
        if not credentials:
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization HTTPBearer header missing.",
            )
        verified_claims = await self.verify_token(credentials.credentials)

        span = trace.get_current_span()
        span.set_attribute(Attributes.USER_AUTH_METHOD, "azure-jwt")
        if oid := verified_claims.get("oid"):
            span.set_attribute(Attributes.USER_ID, oid)
        if name := verified_claims.get("name"):
            span.set_attribute(Attributes.USER_FULL_NAME, name)
        if roles := verified_claims.get("roles"):
            span.set_attribute(Attributes.USER_ROLES, ",".join(roles))
        if email := verified_claims.get("email"):
            span.set_attribute(Attributes.USER_EMAIL, email)

        return self._require_scope_or_role(verified_claims)


class KeycloakJwtAuth(AuthMethod):
    """
    AuthMethod for authorizing requests using JWTs issued by Keycloak.

    Similar to AzureJwtAuth but configured for Keycloak's OIDC endpoints.
    Uses authlib.jose for JWT verification and JWKS handling.

    Example:
        .. code-block:: python

            auth = KeycloakJwtAuth(
                keycloak_url="http://localhost:8080",
                realm="destiny",
                client_id="destiny-repository-client",
                scope=AuthScope.REFERENCE_READER,
            )

            router = APIRouter(
                prefix="/references",
                tags=["references"],
                dependencies=[Depends(auth)]
            )

    """

    def __init__(  # noqa: PLR0913
        self,
        keycloak_url: str,
        realm: str,
        client_id: str,
        scope: StrEnum | None = None,
        role: StrEnum | None = None,
        cache_ttl: int = CACHE_TTL,
        issuer_url: str | None = None,
    ) -> None:
        """
        Initialize the Keycloak JWT auth dependency.

        Args:
            keycloak_url: The base URL of the Keycloak server (used for JWKS fetching)
            realm: The Keycloak realm name
            client_id: The client ID (audience) for token validation
            scope: The required authorization scope for delegated (user) tokens
            role: The required authorization role for application tokens
            cache_ttl: Time to live for JWKS cache entries, defaults to 24 hours
            issuer_url: Optional separate URL for token issuer validation. Defaults to
                keycloak_url if not provided. Useful when tokens are issued with a
                different URL than the internal JWKS endpoint (e.g., in Docker).

        """
        self.keycloak_url = keycloak_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.scope = scope
        self.role = role
        self.cache: TTLCache = TTLCache(maxsize=1, ttl=cache_ttl)

        issuer_base = (issuer_url or keycloak_url).rstrip("/")
        self.issuer = f"{issuer_base}/realms/{self.realm}"
        self.jwks_uri = (
            f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/certs"
        )

        # Create JWT decoder with claims validation
        self._jwt = JsonWebToken(["RS256"])

    async def verify_token(self, token: str) -> dict[str, Any]:
        """
        Verify the token using JWKS fetched from Keycloak.

        Uses authlib.jose for JWT decoding and JWKS key matching.

        Args:
            token: The JWT to be verified

        Returns:
            The decoded token payload

        Raises:
            AuthError: If token verification fails

        """
        jwks = self.cache.get("jwks")
        cached_jwks = bool(jwks)

        if not jwks:
            jwks = await self._get_keycloak_keys()
            self.cache["jwks"] = jwks

        try:
            claims = self._jwt.decode(
                token,
                jwks,
                claims_options={
                    "iss": {"essential": True, "value": self.issuer},
                    "aud": {"essential": True, "value": self.client_id},
                },
            )
            claims.validate()
            return dict(claims)

        except jose_errors.ExpiredTokenError as exc:
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is expired.",
            ) from exc

        except jose_errors.InvalidClaimError as exc:
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token claims: {exc}",
            ) from exc

        except jose_errors.JoseError as exc:
            # If we had cached JWKS and verification failed,
            # try refreshing the keys (key rotation)
            if cached_jwks:
                self.cache.pop("jwks", None)
                return await self.verify_token(token)
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to parse authentication token.",
            ) from exc

    async def _get_keycloak_keys(self) -> JsonWebKey:
        """Fetch and import JWKS from Keycloak's OIDC endpoint."""
        async with AsyncClient() as client:
            response = await client.get(self.jwks_uri)
            return JsonWebKey.import_key_set(response.json())

    def _require_scope_or_role(self, verified_claims: dict[str, Any]) -> bool:
        """
        Check for required scope or role in the Keycloak token.

        Keycloak tokens have:
        - scope: space-separated string of scopes
        - realm_access.roles: list of realm roles
        - resource_access.{client_id}.roles: list of client roles

        Args:
            verified_claims: The decoded JWT claims

        Returns:
            True if authorization is successful

        Raises:
            AuthError: If required scope/role is not present

        """
        # Check scopes (space-separated string in Keycloak)
        if self.scope and verified_claims.get("scope"):
            scopes = verified_claims["scope"].split()
            if self.scope.value in scopes:
                return True

            raise AuthError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"The scope claim does not contain the required scope "
                f"{self.scope.value}",
            )

        # Check realm roles
        if self.role:
            realm_roles = verified_claims.get("realm_access", {}).get("roles", [])
            if self.role.value in realm_roles:
                return True

            # Also check client-specific roles
            client_roles = (
                verified_claims.get("resource_access", {})
                .get(self.client_id, {})
                .get("roles", [])
            )
            if self.role.value in client_roles:
                return True

            raise AuthError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"The roles claim does not contain the required role "
                f"{self.role.value}",
            )

        raise AuthError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Neither scope nor roles claim was found in the bearer token.",
        )

    async def __call__(
        self,
        request: Request,  # noqa: ARG002
        credentials: HTTPAuthorizationCredentials | None,
    ) -> bool:
        """Authenticate the request using Keycloak JWT."""
        if not credentials:
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization HTTPBearer header missing.",
            )

        verified_claims = await self.verify_token(credentials.credentials)

        # Set telemetry attributes
        span = trace.get_current_span()
        span.set_attribute(Attributes.USER_AUTH_METHOD, "keycloak-jwt")

        if sub := verified_claims.get("sub"):
            span.set_attribute(Attributes.USER_ID, sub)
        if name := verified_claims.get("name"):
            span.set_attribute(Attributes.USER_FULL_NAME, name)
        if email := verified_claims.get("email"):
            span.set_attribute(Attributes.USER_EMAIL, email)

        # Get roles from realm_access for telemetry
        realm_access = verified_claims.get("realm_access", {})
        if roles := realm_access.get("roles"):
            span.set_attribute(Attributes.USER_ROLES, ",".join(roles))

        return self._require_scope_or_role(verified_claims)


class SuccessAuth(AuthMethod):
    """
    A fake auth class that will always respond successfully.

    Intended for use in local environments and for testing.

    Not for production use!
    """

    _succeed: bool

    def __init__(self) -> None:
        """Initialize the fake auth callable."""

    async def __call__(
        self,
        request: Request,  # noqa: ARG002
        credentials: Annotated[  # noqa: ARG002
            HTTPAuthorizationCredentials | None,
            Depends(security),
        ],
    ) -> bool:
        """Return true."""
        span = trace.get_current_span()
        span.set_attribute(Attributes.USER_AUTH_METHOD, "bypass")

        return True


def choose_auth_strategy(
    application_id: str,
    auth_scope: AuthScope | None = None,
    auth_role: AuthRole | None = None,
    *,
    bypass_auth: bool,
) -> AuthMethod:
    """Choose a strategy for our authorization based on configured provider."""
    if bypass_auth:
        return SuccessAuth()

    # Check auth provider setting
    if settings.auth_provider == "keycloak":
        if not settings.keycloak_url or not settings.keycloak_client_id:
            msg = (
                "Keycloak auth provider selected but keycloak_url or "
                "keycloak_client_id is not configured"
            )
            raise ValueError(msg)
        return KeycloakJwtAuth(
            keycloak_url=settings.keycloak_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_client_id,
            scope=auth_scope,
            role=auth_role,
            issuer_url=settings.keycloak_issuer_url,
        )

    # Default to Azure AD
    return AzureJwtAuth(
        application_id=application_id,
        scope=auth_scope,
        role=auth_role,
    )


class HMACMultiClientAuth(AuthMethod):
    """
    Adds HMAC auth that supports authenticating with multiple clients.

    Uses a client secret lookup function provided at initialisation,
    which is then called with the client_id provided in the request header.
    """

    def __init__(
        self,
        get_client_secret: Callable[[UUID], Awaitable[str]],
        client_type: HMACClientType,
    ) -> None:
        """
        Initialize with a client secret lookup callable.

        :param get_client_secret: Callable that will return the client secret an id.
        :type get_client_secret: Callable[[UUID], Awaitable[str]]
        :param client_type: The type of client this auth method is for.
            Only used for telemetry.
        :type client_type: HMACClientType
        """
        self.get_secret = get_client_secret
        self._type = client_type

    async def __call__(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = None,  # noqa: ARG002
    ) -> bool:
        """Perform Authorization check."""
        auth_headers = destiny_sdk.auth.HMACAuthorizationHeaders.from_request(request)

        span = trace.get_current_span()
        span.set_attribute(
            Attributes.USER_ID, f"{self._type.value}:{auth_headers.client_id}"
        )
        span.set_attribute(Attributes.USER_AUTH_METHOD, "hmac")

        request_body = await request.body()

        try:
            secret_key = await self.get_secret(auth_headers.client_id)
        except NotFoundError as exc:
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    f"{self._type} client {auth_headers.client_id} does not exist."
                ),
            ) from exc

        expected_signature = destiny_sdk.client.create_signature(
            secret_key=secret_key,
            request_body=request_body,
            client_id=auth_headers.client_id,
            timestamp=auth_headers.timestamp,
        )

        if not hmac.compare_digest(auth_headers.signature, expected_signature):
            raise AuthError(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature is invalid."
            )

        return True


def choose_hmac_auth_strategy(
    get_client_secret: Callable[[UUID], Awaitable[str]],
    client_type: HMACClientType,
) -> AuthMethod:
    """Choose an HMAC auth method."""
    if settings.running_locally:
        return SuccessAuth()

    return HMACMultiClientAuth(
        get_client_secret=get_client_secret, client_type=client_type
    )


class HybridAuth(AuthMethod):
    """
    An auth method that accepts both JWT (Bearer token) and HMAC authentication.

    This class tries JWT authentication first (if Bearer token is present),
    then falls back to HMAC authentication if no Bearer token or JWT fails.

    Example:
        .. code-block:: python

            def hybrid_auth_dependency(
                request: Request,
                robot_service: Annotated[RobotService, Depends(robot_service)],
                credentials: Annotated[
                    HTTPAuthorizationCredentials | None,
                    Depends(security)
                ],
            ) -> bool:
                hybrid_auth = HybridAuth(
                    jwt_auth=AzureJwtAuth(
                        application_id=settings.application_id,
                        scope=AuthScopes.READ,
                    ),
                    hmac_auth=HMACMultiClientAuth(
                        get_client_secret=robot_service.get_robot_secret_standalone
                    ),
                )
                return await hybrid_auth.authenticate(request, credentials)

            @router.get("/", dependencies=[Depends(hybrid_auth_dependency)])
            async def get_data():
                pass

    """

    def __init__(
        self,
        jwt_auth: AzureJwtAuth | KeycloakJwtAuth,
        hmac_auth: HMACMultiClientAuth,
    ) -> None:
        """
        Initialize hybrid auth with both JWT and HMAC auth methods.

        Note both methods use the Authentication header, so we will never
        attempt to use both at the same time.

        :param jwt_auth: The JWT authentication method to use (Azure or Keycloak)
        :param hmac_auth: The HMAC authentication method to use
        """
        self._jwt_auth = jwt_auth
        self._hmac_auth = hmac_auth

    async def __call__(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None,
    ) -> bool:
        """Authenticate using either JWT or HMAC."""
        if credentials and credentials.credentials:
            return await self._jwt_auth(request=request, credentials=credentials)

        return await self._hmac_auth(request=request, credentials=credentials)


def choose_hybrid_auth_strategy(  # noqa: PLR0913
    application_id: str,
    jwt_scope: AuthScope | None,
    jwt_role: AuthRole | None,
    get_client_secret: Callable[[UUID], Awaitable[str]],
    hmac_client_type: HMACClientType,
    *,
    bypass_auth: bool,
) -> AuthMethod:
    """
    Create a hybrid auth dependency function.

    :param application_id: Azure application ID for JWT validation
    :param jwt_scope: The required JWT scope/role
    :param get_client_secret: Function to get HMAC client secrets
    :param bypass_auth: Whether to bypass auth (for local development)
    :return: FastAPI dependency function
    """
    if bypass_auth:
        return SuccessAuth()

    # Choose JWT auth based on provider
    if settings.auth_provider == "keycloak":
        if not settings.keycloak_url or not settings.keycloak_client_id:
            msg = (
                "Keycloak auth provider selected but keycloak_url or "
                "keycloak_client_id is not configured"
            )
            raise ValueError(msg)
        jwt_auth: AzureJwtAuth | KeycloakJwtAuth = KeycloakJwtAuth(
            keycloak_url=settings.keycloak_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_client_id,
            scope=jwt_scope,
            role=jwt_role,
            issuer_url=settings.keycloak_issuer_url,
        )
    else:
        jwt_auth = AzureJwtAuth(
            application_id=application_id,
            scope=jwt_scope,
            role=jwt_role,
        )

    return HybridAuth(
        jwt_auth=jwt_auth,
        hmac_auth=HMACMultiClientAuth(
            get_client_secret=get_client_secret,
            client_type=hmac_client_type,
        ),
    )
