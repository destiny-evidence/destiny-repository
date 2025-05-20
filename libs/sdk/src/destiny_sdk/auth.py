"""
Authentication assistance methods.

This module is based on the following references:
* https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#validate-tokens
* https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation
* https://github.com/Azure-Samples/ms-identity-python-webapi-azurefunctions/blob/master/Function/secureFlaskApp/__init__.py
* https://github.com/425show/fastapi_microsoft_identity/blob/main/fastapi_microsoft_identity/auth_service.py
"""

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, Protocol

from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import AsyncClient
from jose import exceptions, jwt

# Dependency to get the token from the Authorization header
# `auto_error=False` allows us to provide a more meaningful error message
# when the token is missing.
# Also allows the ignoring bearer tokens when during testing
# or in development environments
security = HTTPBearer(auto_error=False)


class AuthException(HTTPException):
    """
    An exception related to HTTP authentication.

    Raised by implementations of the AuthMethod protocol.

    ## Example

    ```python
    raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to parse authentication token.",
            )
    ```
    """


class AuthMethod(Protocol):
    """

    Protocol for auth methods, enforcing the implmentation of __call__().

    Inherit from this class when adding an auth implementation.

    This allows FastAPI to call class instances as depenedencies in FastAPI routes,
    see https://fastapi.tiangolo.com/advanced/advanced-dependencies

    ## Example

    ```python

    auth = AuthMethod()

    router = APIRouter(
        prefix="/imports", tags=["imports"], dependencies=[Depends(auth)]
    )
    ```
    """

    async def __call__(
        self,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> bool:
        """
        Callable interface to allow use as a dependency.

        Args:
        credentials (HTTPAuthorizationCredentials): The bearer token provided in the
                                                    request (as a dependency)

        """
        raise NotImplementedError


class StrategyAuth(AuthMethod):
    """
    A meta-auth method which chooses the auth method at runtime.

    Calls the auth strategy selector every time the dependency is invoked.

    ## Example

    ```python

    def auth_strategy():
        return AzureJwtAuth(
            tenant_id=settings.tenant_id,
            application_id=settings.application_id,
            scope=AuthScopes.READ,
        )

    strategy_auth = StrategyAuth(selector=auth_strategy)

    router = APIRouter(
        prefix="/imports", tags=["imports"], dependencies=[Depends(strategy_auth)]
    )
    ```
    """

    _selector: Callable[[], AuthMethod]

    def __init__(
        self,
        selector: Callable[[], AuthMethod],
    ) -> None:
        """
        Initialise strategy.

        Args:
        - selector (Callable[[], str]): A callable which returns a string which
        will be used to choose the correct function.

        """
        self._selector = selector

    def _get_strategy(self) -> AuthMethod:
        return self._selector()

    async def __call__(
        self,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> bool:
        """Callable interface to allow use as a dependency."""
        return await self._get_strategy()(credentials=credentials)


class CachingStrategyAuth(StrategyAuth):
    """
    A subclass of StrategyAuth which caches the selected strategy across calls.

    ## Example

    ```python

    def auth_strategy():
        return AzureJwtAuth(
            tenant_id=settings.tenant_id,
            application_id=settings.application_id,
            scope=AuthScopes.READ,
        )

    caching_auth = CachingStrategyAuth(selector=auth_strategy)

    router = APIRouter(
        prefix="/imports", tags=["imports"], dependencies=[Depends(caching_auth)]
    )
    ```

    """

    _cached_strategy: AuthMethod | None

    def __init__(self, selector: Callable[[], AuthMethod]) -> None:
        """
        Initialise strategy.

        Args:
        - selector (Callable[[], AuthMethod]): A callable which returns the AuthMethod
        to be used.

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

    Any client communicating with your robot requires assignment to the app role
    that matches the auth scope it wishes to use. Azure will provide these scopes
    back in the JWT.

    ## Example

    ```python

    class AuthScopes(StrEnum):
        READ = "read"

    def auth_strategy():
        return AzureJwtAuth(
            tenant_id=settings.tenant_id,
            application_id=settings.application_id,
            scope=AuthScopes.READ,
        )

    caching_auth = CachingStrategyAuth(selector=auth_strategy)

    router = APIRouter(
        prefix="/imports", tags=["imports"], dependencies=[Depends(caching_auth)]
    )
    ```
    """

    def __init__(
        self,
        tenant_id: str,
        application_id: str,
        scope: StrEnum,
        cache_ttl: int = 60 * 60 * 24,
    ) -> None:
        """
        Initialize the dependency.

        Args:
        tenant_id (str): The Azure AD tenant ID
        application_id (str): The Azure AD application ID
        scope (StrEnum): The authorization scope for the API
        cache_ttl (int): Time to live for cache entries, defaults to 24 hours.

        """
        self.tenant_id = tenant_id
        self.api_audience = f"api://{application_id}"
        self.scope = scope
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
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to parse authentication token.",
            ) from exc

        if rsa_key:
            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=["RS256"],
                    audience=self.api_audience,
                    issuer=f"https://sts.windows.net/{
                        self.tenant_id}/",
                )
            except exceptions.ExpiredSignatureError as exc:
                raise AuthException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is expired."
                ) from exc
            except exceptions.JWTClaimsError as exc:
                raise AuthException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect claims, please check the audience and issuer.",
                ) from exc
            except Exception as exc:
                if cached_jwks:
                    self.cache.pop("jwks", None)
                    return await self.verify_token(token)
                raise AuthException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unable to parse authentication token.",
                ) from exc
            else:
                return payload
        raise AuthException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find appropriate key.",
        )

    async def _get_microsoft_keys(self) -> Any:  # noqa: ANN401
        async with AsyncClient() as client:
            response = await client.get(
                f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"
            )
            return response.json()

    def _require_scope(
        self, required_scope: StrEnum, verified_claims: dict[str, Any]
    ) -> bool:
        if verified_claims.get("roles"):
            for scope in verified_claims["roles"]:
                if scope.lower() == required_scope.value.lower():
                    return True

            raise AuthException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"IDW10203: The app permissions (role) claim does not contain the scope {required_scope.value}",  # noqa: E501
            )
        raise AuthException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IDW10201: No app permissions (role) claim was found in the bearer token",  # noqa: E501
        )

    async def __call__(
        self,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> bool:
        """Authenticate the request."""
        if not credentials:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization HTTPBearer header missing.",
            )
        verified_claims = await self.verify_token(credentials.credentials)
        return self._require_scope(self.scope, verified_claims)


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
        credentials: Annotated[  # noqa: ARG002
            HTTPAuthorizationCredentials | None,
            Depends(security),
        ],
    ) -> bool:
        """Return true."""
        return True
