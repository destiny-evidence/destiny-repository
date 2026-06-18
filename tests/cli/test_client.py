"""Tests for the CLI client factory and argument parser."""

import httpx
import pytest
from destiny_sdk.client import OAuthMiddleware

from app.core.config import Environment
from cli.client import ApiArgumentParser, get_client


@pytest.mark.parametrize("env", [Environment.LOCAL, Environment.TEST])
def test_local_envs_default_to_localhost_without_auth(env: Environment) -> None:
    """Local/test default to localhost and attach no OAuth."""
    client = get_client(env)
    assert str(client.base_url) == "http://127.0.0.1:8000/v1/"
    assert not isinstance(client.auth, OAuthMiddleware)


def test_url_overrides_local_default() -> None:
    """An explicit url replaces the localhost default."""
    client = get_client(Environment.LOCAL, "https://example.com")
    assert str(client.base_url) == "https://example.com/v1/"


def test_real_env_attaches_oauth() -> None:
    """Real envs delegate authentication to the SDK's OAuthMiddleware."""
    client = get_client(Environment.PRODUCTION)
    assert isinstance(client.auth, OAuthMiddleware)


def test_parser_attaches_client_and_defaults_to_local() -> None:
    """Parsing yields a ready httpx client, defaulting to local/no-auth."""
    args = ApiArgumentParser().parse_args([])
    assert args.env == Environment.LOCAL
    assert isinstance(args.client, httpx.Client)
    assert not isinstance(args.client.auth, OAuthMiddleware)


def test_parser_passes_url_through() -> None:
    """``--url`` flows into the resolved client's base URL."""
    args = ApiArgumentParser().parse_args(["--url", "https://example.com"])
    assert str(args.client.base_url) == "https://example.com/v1/"
