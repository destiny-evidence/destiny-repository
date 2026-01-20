"""Add authentication for requests sent to destiny repo."""

from collections.abc import Generator
from typing import TYPE_CHECKING

import httpx
from destiny_sdk.keycloak_auth import KeycloakAuthCodeFlow

from app.core.config import Environment
from app.utils.get_token import get_token
from cli.config import get_settings

if TYPE_CHECKING:
    from cli.config import Settings


class CLIAuth(httpx.Auth):
    """
    Client that adds a Bearer token to a request.

    Supports both Azure AD and Keycloak authentication based on the
    `auth_provider` setting in the CLI config.
    """

    def __init__(self, env: Environment) -> None:
        """
        Initialize the client.

        :param env: the environment the CLI is running in
        :type env: Environment
        """
        self.env = env

    def _get_azure_token(self, settings: "Settings") -> str:
        """Get an Azure AD token."""
        return get_token(
            cli_client_id=settings.cli_client_id,
            azure_login_url=str(settings.azure_login_url),
            azure_application_id=settings.azure_application_id,
        )

    def _get_keycloak_token(self, settings: "Settings") -> str:
        """Get a Keycloak token."""
        if not settings.keycloak_url:
            msg = "keycloak_url must be set when using Keycloak authentication"
            raise RuntimeError(msg)

        flow = KeycloakAuthCodeFlow(
            keycloak_url=settings.keycloak_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_client_id,
        )
        token_response = flow.authenticate()
        return token_response.access_token

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Add a Bearer token to the request if we're not in a test environment."""
        if self.env not in (Environment.LOCAL, Environment.TEST):
            settings = get_settings(self.env)

            if settings.auth_provider == "keycloak":
                access_token = self._get_keycloak_token(settings)
            else:
                access_token = self._get_azure_token(settings)

            request.headers["Authorization"] = f"Bearer {access_token}"
        yield request
