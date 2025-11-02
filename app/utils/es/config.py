"""Config for ES Operations."""

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Environment, ESConfig, LogLevel, OTelConfig


class Settings(BaseSettings):
    """Settings model for ES operations."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    project_root: Path = Path(__file__).joinpath("../../../..").resolve()

    es_config: ESConfig
    otel_config: OTelConfig | None = None
    otel_enabled: bool = False
    app_name: str
    env: Environment
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="The log level for es operations.",
    )

    @property
    def running_locally(self) -> bool:
        """Return True if the migration is running locally."""
        return self.env in (Environment.LOCAL, Environment.TEST)

    @property
    def pyproject_toml(self) -> dict[str, Any]:
        """Get the contents of pyproject.toml."""
        return tomllib.load((self.project_root / "pyproject.toml").open("rb"))

    @property
    def app_version(self) -> str:
        """Get the version from pyproject.toml."""
        return self.pyproject_toml["project"]["version"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
