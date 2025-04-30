"""API config parsing and model."""

from functools import lru_cache
from pathlib import Path

from pydantic import UUID4, Field, HttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    db_url: PostgresDsn = Field(..., description="The URL for the API database.")
    project_root: Path = Path(__file__).joinpath("../../..").resolve()

    azure_application_id: str
    azure_login_url: HttpUrl = HttpUrl("https://login.microsoftonline.com")
    azure_tenant_id: str
    message_broker_url: str | None = None
    message_broker_namespace: str | None = None
    message_broker_queue_name: str = "taskiq"
    cli_client_id: str | None = None

    # Temporary robot configuration, replace with db table later.
    known_robots: dict[UUID4, HttpUrl] = Field(
        default={}, description="mapping of known robot ids to urls."
    )

    env: str = Field("production", description="The environment the app is running in.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()  # type: ignore[call-arg]
