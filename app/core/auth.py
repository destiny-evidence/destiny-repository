"""Tools for authorising requests."""

from collections.abc import Callable
from enum import Enum
from typing import Annotated, Any, Protocol

from cachetools import TTLCache
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import AsyncClient
from jose import exceptions, jwt

from app.core.exceptions.auth_exception import AuthException

# This module is based on the following references:
# * https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#validate-tokens
# * https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation
# * https://github.com/Azure-Samples/ms-identity-python-webapi-azurefunctions/blob/master/Function/secureFlaskApp/__init__.py
# * https://github.com/425show/fastapi_microsoft_identity/blob/main/fastapi_microsoft_identity/auth_service.py


# Dependency to get the token from the Authorization header
security = HTTPBearer()


class AuthScopes(Enum):
    """Enum describing the available auth scopes that we understand."""

    READ_ALL = "read.all"
    IMPORT = "import"


CACHE_TTL = 60 * 60 * 24  # 24 hours


class AuthMethod(Protocol):
    """Protocol for auth methods."""

    async def __call__(
        self, credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]
    ) -> bool:
        """Callable interface to allow use as a dependency."""
        raise NotImplementedError


class StrategyAuth(AuthMethod):
    """A meta-auth method which chooses the auth method at runtime."""

    _selector: Callable[[], str]
    _strategies: dict[str, AuthMethod]

    def __init__(
        self,
        strategies: dict[str, AuthMethod],
        selector: Callable[[], str],
    ) -> None:
        """
        Initialise strategy.

        Args:
        - strategies (dict[str, AuthMethod]): A dictionary of AuthMethod values,
        keyed with the name which will be returned by the selector.
        - selector (Callable[[], str]): A callable which returns a string which
        will be used to choose the correct function.

        """
        self._strategies = strategies
        self._selector = selector

    def _get_strategy(self) -> AuthMethod:
        strategy_name = self._selector()
        chosen = self._strategies.get(strategy_name)
        if not chosen:
            available = self._strategies.keys()
            message = f"""
Could not find strategy '{strategy_name}'. Available strategies: {available}
"""
            raise RuntimeError(message)
        return chosen

    async def __call__(
        self, credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]
    ) -> bool:
        """Callable interface to allow use as a dependency."""
        return await self._get_strategy()(credentials=credentials)


class CachingStrategyAuth(StrategyAuth):
    """A subclass of StrategyAuth which caches the selected strategy across calls."""

    _cached_strategy: AuthMethod | None

    def __init__(
        self, strategies: dict[str, AuthMethod], selector: Callable[[], str]
    ) -> None:
        """
        Initialise strategy.

        Args:
        - strategies (dict[str, AuthMethod]): A dictionary of AuthMethod values,
        keyed with the name which will be returned by the selector.
        - selector (Callable[[], str]): A callable which returns a string which
        will be used to choose the correct function.

        """
        super().__init__(strategies, selector)
        self._cached_strategy = None

    def _get_strategy(self) -> AuthMethod:
        if self._cached_strategy:
            return self._cached_strategy
        self._cached_strategy = super()._get_strategy()
        return self._cached_strategy

    def reset(self) -> None:
        """Reset the cached strategy so it is fetch at next call."""
        self._cached_strategy = None


class SuccessAuth(AuthMethod):
    """A fake auth class that will always respond how you tell it to."""

    _succeed: bool

    def __init__(self) -> None:
        """
        Initialize the fake auth callable.

        Args:
        - always_succeed (bool): Whether or not we should always succeed. If not,
        we will always fail by raising an AuthException.

        """

    async def __call__(
        self,
        credentials: Annotated[  # noqa: ARG002
            HTTPAuthorizationCredentials, Depends(security)
        ],
    ) -> bool:
        """Return true or raise an AuthException."""
        return True


class AzureJwtAuth(AuthMethod):
    """Dependency for authorizing requests using the JWT provided by Azure."""

    def __init__(self, tenant_id: str, application_id: str, scope: AuthScopes) -> None:
        """
        Initialize the dependency.

        Args:
        tenant_id (str): The Azure AD tenant ID
        application_id (str): The Azure AD application ID
        scope (AuthScopes): The authorization scope for the API

        """
        self.tenant_id = tenant_id
        self.api_audience = f"api://{application_id}"
        self.scope = scope
        self.cache: TTLCache = TTLCache(maxsize=1, ttl=CACHE_TTL)

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
        self, required_scope: AuthScopes, verified_claims: dict[str, Any]
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

    # This allows FastAPI to call instances of this class as dependencies in
    # FastAPI routes.  See https://fastapi.tiangolo.com/advanced/advanced-dependencies
    async def __call__(
        self, credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]
    ) -> bool:
        """
        Call the instance as a dependency.

        Args:
        credentials (HTTPAuthorizationCredentials): The bearer token provided in the
                                                    request (as a dependency)

        """
        verified_claims = await self.verify_token(credentials.credentials)
        return self._require_scope(self.scope, verified_claims)
