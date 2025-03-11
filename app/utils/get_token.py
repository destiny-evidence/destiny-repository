"""A utility to grab the token from Azure to use in development."""

# ruff: noqa: T201
from msal import PublicClientApplication

from app.core.config import get_settings

settings = get_settings()


def get_token() -> str:
    """Fetch a token for the app from Azure."""
    if not settings.cli_client_id:
        msg = "No cli_client_id has been defined."
        raise RuntimeError(msg)

    app = PublicClientApplication(
        settings.cli_client_id,
        authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
        client_credential=None,
    )

    result = app.acquire_token_interactive(
        scopes=[f"api://{settings.azure_application_id}/.default"]
    )

    return result["access_token"]


if __name__ == "__main__":
    result = get_token()

    print("Here is your access token:")
    print(result)
