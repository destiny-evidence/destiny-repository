"""Tests for CLI Settings defaulting."""

import os

import pytest

from app.core.config import Environment
from cli.config import DEFAULT_REPOSITORY_URLS, Settings


@pytest.fixture(autouse=True)
def _no_clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop ``Settings.__init__`` from wiping pytest's environment variables."""
    monkeypatch.setattr(os.environ, "clear", lambda: None)


def test_default_repository_urls_cover_all_environments() -> None:
    """Every Environment value has a default URL — guards against new envs."""
    for env in Environment:
        assert env in DEFAULT_REPOSITORY_URLS


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (Environment.LOCAL, "http://127.0.0.1:8000/"),
        (Environment.TEST, "http://127.0.0.1:8000/"),
        (Environment.DEVELOPMENT, "https://api.dev.evidence-repository.org/"),
        (Environment.STAGING, "https://api.staging.evidence-repository.org/"),
        (Environment.PRODUCTION, "https://api.evidence-repository.org/"),
    ],
)
def test_settings_uses_per_env_default_url(env: Environment, expected: str) -> None:
    """When no env override is set, Settings picks the per-env default URL."""
    settings = Settings(env=env)
    assert str(settings.destiny_repository_url) == expected


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit DESTINY_REPOSITORY_URL env var wins over the per-env default."""
    monkeypatch.setenv("DESTINY_REPOSITORY_URL", "https://example.com/api")
    settings = Settings(env=Environment.PRODUCTION)
    assert str(settings.destiny_repository_url) == "https://example.com/api"
