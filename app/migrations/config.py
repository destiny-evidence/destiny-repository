"""Alembic config parsing and model."""

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import (
    DatabaseConfig,
    Environment,
    FeatureFlags,
    LogLevel,
    OTelConfig,
)


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    project_root: Path = Path(__file__).joinpath("../../..").resolve()

    feature_flags: FeatureFlags = FeatureFlags()

    db_config: DatabaseConfig
    otel_config: OTelConfig | None = None
    otel_enabled: bool = False

    env: Environment = Field(
        default=Environment.PRODUCTION,
        description="The environment the app is running in.",
    )

    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="The log level for the application.",
    )

    @property
    def pyproject_toml(self) -> dict[str, Any]:
        """Get the contents of pyproject.toml."""
        return tomllib.load((self.project_root / "pyproject.toml").open("rb"))

    @property
    def app_version(self) -> str:
        """Get the application version from pyproject.toml."""
        return self.pyproject_toml["project"]["version"]

    @property
    def trace_repr(self) -> str:
        """Get a string representation of the config for tracing."""
        return f"feature_flags={self.feature_flags.model_dump_json()}"

    @property
    def running_locally(self) -> bool:
        """Return True if the app is running locally."""
        return self.env in (Environment.LOCAL, Environment.TEST)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
