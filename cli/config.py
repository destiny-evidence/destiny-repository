"""Config for CLI Tool."""

import os

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Environment

DEFAULT_REPOSITORY_URLS: dict[Environment, str] = {
    Environment.LOCAL: "http://127.0.0.1:8000",
    Environment.TEST: "http://127.0.0.1:8000",
    Environment.DEVELOPMENT: "https://api.dev.evidence-repository.org",
    Environment.STAGING: "https://api.staging.evidence-repository.org",
    Environment.PRODUCTION: "https://api.evidence-repository.org",
}


class Settings(BaseSettings):
    """Settings model for CLI."""

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    destiny_repository_url_override: HttpUrl | None = Field(
        default=None,
        validation_alias="destiny_repository_url",
    )
    env: Environment | None = None

    def __init__(self, env: Environment) -> None:
        """Initialize the CLI settings, ignoring existing environment variables."""
        os.environ.clear()
        super().__init__(_env_file=f"cli/.env.{env.value}")
        self.env = env

    @property
    def destiny_repository_url(self) -> HttpUrl:
        """Resolved API base URL: override if provided, else per-env default."""
        if self.destiny_repository_url_override is not None:
            return self.destiny_repository_url_override
        if self.env is None:
            msg = "env must be set"
            raise RuntimeError(msg)
        return HttpUrl(DEFAULT_REPOSITORY_URLS[self.env])


def get_settings(env: Environment) -> Settings:
    """Get settings object."""
    return Settings(env=env)  # type: ignore[call-arg]
