"""Add authentication for requests sent to destiny repo."""

from collections.abc import Generator
from typing import Literal, cast

import httpx
from destiny_sdk.client import OAuthMiddleware

from app.core.config import Environment


class CLIAuth(httpx.Auth):
    """Client that adds a Bearer token to a request via the SDK OAuthMiddleware."""

    def __init__(self, env: Environment) -> None:
        """
        Initialize the client.

        :param env: the environment the CLI is running in
        :type env: Environment
        """
        self.env = env
        self._inner: OAuthMiddleware | None = None
        if env not in (Environment.LOCAL, Environment.TEST):
            self._inner = OAuthMiddleware(
                env=cast(Literal["development", "staging", "production"], env.value),
            )

    def auth_flow(
        self,
        request: httpx.Request,
    ) -> Generator[httpx.Request, httpx.Response]:
        """Add a Bearer token to the request unless we're in a test environment."""
        if self._inner is None:
            yield request
            return
        yield from self._inner.auth_flow(request)
