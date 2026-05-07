"""Smoke tests for the CLI's authentication wiring."""

import httpx
import pytest
from destiny_sdk.client import OAuthMiddleware

from app.core.config import Environment
from cli.auth import CLIAuth


def test_environment_values_match_sdk_env_literal() -> None:
    """CLIAuth passes Environment.value to OAuthMiddleware's env literal."""
    assert Environment.DEVELOPMENT.value == "development"
    assert Environment.STAGING.value == "staging"
    assert Environment.PRODUCTION.value == "production"


@pytest.mark.parametrize(
    "env",
    [Environment.DEVELOPMENT, Environment.STAGING, Environment.PRODUCTION],
)
def test_cliauth_real_env_wires_oauth_middleware(env: Environment) -> None:
    """Real environments construct an OAuthMiddleware delegate."""
    auth = CLIAuth(env=env)
    assert isinstance(auth._inner, OAuthMiddleware)  # noqa: SLF001


@pytest.mark.parametrize("env", [Environment.LOCAL, Environment.TEST])
def test_cliauth_skips_auth_in_non_real_envs(env: Environment) -> None:
    """LOCAL and TEST environments yield the request without an auth header."""
    auth = CLIAuth(env=env)
    assert auth._inner is None  # noqa: SLF001

    request = httpx.Request("GET", "https://example.com/")
    flow = auth.auth_flow(request)
    yielded = next(flow)
    assert "Authorization" not in yielded.headers

    with pytest.raises(StopIteration):
        next(flow)
