"""Tools for authorising requests."""

from enum import StrEnum

from destiny_sdk.auth import AuthMethod, AzureJwtAuth, SuccessAuth

CACHE_TTL = 60 * 60 * 24  # 24 hours


class AuthScopes(StrEnum):
    """Enum describing the available auth scopes that we understand."""

    IMPORT = "import"
    REFERENCE_READER = "reference.reader"
    REFERENCE_WRITER = "reference.writer"
    ROBOT = "robot"


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
