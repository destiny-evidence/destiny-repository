"""Tools for authorising requests."""

from enum import Enum
from typing import Annotated, Any

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


class AzureJwtAuth:
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
