"""Config for ES Operations."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import TOML, Environment, ESConfig, LogLevel, OTelConfig


class Settings(BaseSettings):
    """Settings model for ES operations."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    toml: TOML = TOML(toml_path=Path(__file__).joinpath("../../../..").resolve())

    es_config: ESConfig
    otel_config: OTelConfig | None = None
    otel_enabled: bool = False
    app_name: str
    env: Environment
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="The log level for es operations.",
    )

    reindex_status_polling_interval: int = 5 * 60  # 5min

    @property
    def running_locally(self) -> bool:
        """Return True if the migration is running locally."""
        return self.env in Environment.local_envs()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
