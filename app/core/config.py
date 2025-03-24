"""API config parsing and model."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    db_url: PostgresDsn = Field(..., description="The URL for the API database.")
    project_root: Path = Path(__file__).joinpath("../../..").resolve()

    azure_application_id: str
    azure_login_url: HttpUrl = HttpUrl("https://login.microsoftonline.com")
    azure_tenant_id: str
    cli_client_id: str | None = None

    env: str = Field("dev", description="The environment the app is running in.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()  # type: ignore[call-arg]
