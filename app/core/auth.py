"""Tools for authorising requests."""

from enum import StrEnum

from destiny_sdk.auth import AuthMethod, AzureJwtAuth, SuccessAuth
from fastapi import HTTPException, Request, status

from app.core.config import Environment

CACHE_TTL = 60 * 60 * 24  # 24 hours


class AuthScopes(StrEnum):
    """Enum describing the available auth scopes that we understand."""

    IMPORT = "import"
    REFERENCE_READER = "reference.reader"
    REFERENCE_WRITER = "reference.writer"
    ROBOT = "robot"


def choose_auth_strategy(
    environment: Environment,
    tenant_id: str,
    application_id: str,
    auth_scope: AuthScopes,
) -> AuthMethod:
    """Choose a strategy for our authorization."""
    if environment in (Environment.LOCAL, Environment.TEST):
        return SuccessAuth()

    return AzureJwtAuth(
        tenant_id=tenant_id,
        application_id=application_id,
        scope=auth_scope,
    )


def create_signature() -> str:
    """Create an HMAC signature."""
    return "so fake for now."


class HMACAuth:
    """Adds HMAC auth when used as a router or endpoint dependency."""

    async def __call__(self, request: Request) -> bool:
        """Perform Authorization check."""
        if not self._verify_signature(request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authorized"
            )

        return True

    def _verify_signature(self, request: Request) -> bool:
        return create_signature() == request.headers.get("Authorization")
