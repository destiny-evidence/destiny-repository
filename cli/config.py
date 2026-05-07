"""Config for CLI Tool."""

import os

from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Environment


class Settings(BaseSettings):
    """Settings model for CLI."""

    def __init__(self, env: Environment) -> None:
        """Initialize the CLI settings, ignoring existing environment variables."""
        os.environ.clear()
        super().__init__(_env_file=f"cli/.env.{env.value}")
        self.env = env

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    destiny_repository_url: HttpUrl = HttpUrl("http://127.0.0.1:8000")
    env: Environment | None = None


def get_settings(env: Environment) -> Settings:
    """Get settings object."""
    return Settings(env=env)  # type: ignore[call-arg]
