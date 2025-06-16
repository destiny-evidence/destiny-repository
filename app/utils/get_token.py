"""A utility to grab the token from Azure to use in development."""

# ruff: noqa: T201
from msal import PublicClientApplication

from app.core.config import get_settings

settings = get_settings()


def get_token(
    cli_client_id: str | None,
    azure_login_url: str,
    azure_tenant_id: str,
    azure_application_id: str,
) -> str:
    """Fetch a token for the app from Azure."""
    if not cli_client_id:
        msg = "No cli_client_id has been defined."
        raise RuntimeError(msg)

    if not azure_login_url:
        msg = "No azure_login_url has been defined."
        raise RuntimeError(msg)

    app = PublicClientApplication(
        cli_client_id,
        authority=f"{azure_login_url}{azure_tenant_id}",
        client_credential=None,
    )

    result = app.acquire_token_interactive(
        scopes=[f"api://{azure_application_id}/.default"]
    )

    return result["access_token"]


if __name__ == "__main__":
    result = get_token(
        cli_client_id=settings.cli_client_id,
        azure_login_url=str(settings.azure_login_url),
        azure_tenant_id=settings.azure_tenant_id,
        azure_application_id=settings.azure_application_id,
    )

    print("Here is your access token:")
    print(result)
