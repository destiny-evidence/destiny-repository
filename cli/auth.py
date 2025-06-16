"""Add authentication for requests sent to destiny repo."""

from collections.abc import Generator

import httpx

from app.core.config import Environment
from app.utils.get_token import get_token
from cli.config import get_settings


class CLIAuth(httpx.Auth):
    """Client that adds an HMAC signature to a request."""

    def __init__(self, env: Environment) -> None:
        """
        Initialize the client.

        :param secret_key: the key to use when signing the request
        :type secret_key: str
        """
        self.env = env

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Add a Bearer token to the request if we're not in a test environment."""
        if self.env not in (Environment.LOCAL, Environment.TEST):
            settings = get_settings(self.env)

            access_token = get_token(
                cli_client_id=settings.cli_client_id,
                azure_login_url=str(settings.azure_login_url),
                azure_tenant_id=settings.azure_tenant_id,
                azure_application_id=settings.azure_application_id,
            )

            request.headers["Authorization"] = f"Bearer {access_token}"
        yield request
