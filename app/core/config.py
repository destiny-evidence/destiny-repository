"""API config parsing and model."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, HttpUrl, PostgresDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logger import get_logger
from app.domain.robots.models import RobotConfig

logger = get_logger()


class DatabaseConfig(BaseModel):
    """Database configuration."""

    db_fqdn: str | None = None
    db_user: str | None = None
    db_pass: str | None = None
    db_name: str | None = None
    azure_db_resource_url: HttpUrl | None = None
    db_url: PostgresDsn | None = None
    ssl_mode: str = "prefer"

    @property
    def passwordless(self) -> bool:
        """Return True if the database connection is passwordless."""
        return not (self.db_url or self.db_pass)

    @property
    def connection_string(self) -> str:
        """Return the connection string for the database."""
        if self.db_url:
            url = str(self.db_url)
        elif self.passwordless:
            url = f"postgresql+asyncpg://{self.db_user}@{self.db_fqdn}/{self.db_name}"
        else:
            url = f"postgresql+asyncpg://{self.db_user}:{self.db_pass}@{self.db_fqdn}/{self.db_name}"

        # ssl prefer allows us to connect locally without SSL, overwritable if needed
        return f"{url}?ssl={self.ssl_mode}"

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        """Validate the given parameters."""
        if self.db_url:
            # DB URL provided
            if any(
                (
                    self.db_fqdn,
                    self.db_user,
                    self.db_pass,
                    self.db_name,
                    self.azure_db_resource_url,
                )
            ):
                msg = "If db_url is provided, nothing else should be provided."
                raise ValueError(msg)
        else:
            # DB URL not provided
            if not all((self.db_fqdn, self.db_user, self.db_name)):
                msg = """
If db_url is not provided, db_fqdn, db_user and db_name must be provided."""
                raise ValueError(msg)
            if self.db_pass and self.azure_db_resource_url:
                msg = """
If db_pass is provided, azure_db_resource_url must not be provided."""
                raise ValueError(msg)
            if not self.db_pass and not self.azure_db_resource_url:
                msg = "db_pass not provided, using default azure_db_resource_url."
                logger.warning(msg)
                self.azure_db_resource_url = HttpUrl(
                    "https://ossrdbms-aad.database.windows.net/.default"
                )
        return self


class MinioConfig(BaseModel):
    """Minio configuration."""

    host: str
    access_key: str
    secret_key: str
    bucket: str = "destiny-repository"


class Environment(StrEnum):
    """Environment enum."""

    PRODUCTION = "production"
    DEVELOPMENT = "development"
    LOCAL = "local"
    TEST = "test"


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    project_root: Path = Path(__file__).joinpath("../../..").resolve()

    db_config: DatabaseConfig
    minio_config: MinioConfig | None = None

    azure_application_id: str
    azure_login_url: HttpUrl = HttpUrl("https://login.microsoftonline.com")
    azure_tenant_id: str
    message_broker_url: str | None = None
    message_broker_namespace: str | None = None
    message_broker_queue_name: str = "taskiq"
    cli_client_id: str | None = None
    app_name: str

    # Temporary robot configuration, replace with db table later.
    known_robots: list[RobotConfig] = Field(
        default_factory=list, description="semi-hardcoded robot configuration"
    )

    env: Environment = Field(
        default=Environment.PRODUCTION,
        description="The environment the app is running in.",
    )

    @property
    def running_locally(self) -> bool:
        """Return True if the app is running locally."""
        return self.env in (Environment.LOCAL, Environment.TEST)

    @property
    def default_blob_location(self) -> str:
        """Return the default blob location."""
        return "minio" if self.running_locally else "azure"

    @property
    def default_blob_container(self) -> str:
        """Return the default blob container."""
        if self.running_locally and self.minio_config:
            return self.minio_config.bucket
        return "destiny-repository"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
