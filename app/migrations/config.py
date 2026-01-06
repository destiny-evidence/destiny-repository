"""Alembic config parsing and model."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import (
    TOML,
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

    toml: TOML = TOML(toml_path=Path(__file__).joinpath("../../..").resolve())

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
    def trace_repr(self) -> str:
        """Get a string representation of the config for tracing."""
        return f"feature_flags={self.feature_flags.model_dump_json()}"

    @property
    def running_locally(self) -> bool:
        """Return True if the db migration is running locally."""
        return self.env in Environment.local_envs()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
