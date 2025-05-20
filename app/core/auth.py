"""Tools for authorising requests."""

from typing import Annotated

from destiny_sdk.auth import AuthMethod, AuthScopes, AzureJwtAuth
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# This module is based on the following references:
# * https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#validate-tokens
# * https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation
# * https://github.com/Azure-Samples/ms-identity-python-webapi-azurefunctions/blob/master/Function/secureFlaskApp/__init__.py
# * https://github.com/425show/fastapi_microsoft_identity/blob/main/fastapi_microsoft_identity/auth_service.py


# Dependency to get the token from the Authorization header
# `auto_error=False` allows us to both ignore bearer tokens when using SuccessAuth and
# also provide a more meaningful error message when the token is missing.
security = HTTPBearer(auto_error=False)

CACHE_TTL = 60 * 60 * 24  # 24 hours


def choose_auth_strategy(
    environment: str, tenant_id: str, application_id: str, auth_scope: AuthScopes
) -> AuthMethod:
    """Choose a strategy for our authorization."""
    if environment in ("dev", "test"):
        return SuccessAuth()

    return AzureJwtAuth(
        tenant_id=tenant_id,
        application_id=application_id,
        scope=auth_scope,
    )


class SuccessAuth(AuthMethod):
    """A fake auth class that will always respond successfully."""

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
