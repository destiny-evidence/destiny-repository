"""API config parsing and model."""

from enum import StrEnum, auto
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    PostgresDsn,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logger import get_logger

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
    presigned_url_expiry_seconds: int = 60 * 60  # 1 hour


class AzureBlobConfig(BaseModel):
    """Azure Blob Storage configuration."""

    storage_account_name: str
    container: str
    credential: str | None = None
    presigned_url_expiry_seconds: int = 60 * 60  # 1 hour
    user_delegation_key_duration: int = 60 * 60 * 24  # 1 day

    @property
    def uses_managed_identity(self) -> bool:
        """Return True if the configuration uses managed identity."""
        return self.credential is None

    @property
    def account_url(self) -> str:
        """Return the account URL for Azure Blob Storage."""
        return f"https://{self.storage_account_name}.blob.core.windows.net"


class Environment(StrEnum):
    """Environment enum."""

    PRODUCTION = auto()
    STAGING = auto()
    DEVELOPMENT = auto()
    LOCAL = auto()
    TEST = auto()


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    project_root: Path = Path(__file__).joinpath("../../..").resolve()

    db_config: DatabaseConfig
    minio_config: MinioConfig | None = None
    azure_blob_config: AzureBlobConfig | None = None

    azure_application_id: str
    azure_login_url: HttpUrl = HttpUrl("https://login.microsoftonline.com")
    azure_tenant_id: str
    message_broker_url: str | None = None
    message_broker_namespace: str | None = None
    message_broker_queue_name: str = "taskiq"
    cli_client_id: str | None = None
    app_name: str

    import_batch_retry_count: int = Field(
        default=3,
        description=(
            "Number of times to retry processing an import batch before marking it as "
            "failed. We only retry on errors we are confident can be resolved - eg "
            "network issues or inconsistent database state being loaded in parallel."
        ),
    )

    # Message lock renewal configuration
    message_lock_renewal_duration: int = Field(
        default=3600 * 3,  # 3 hours
        description=(
            "Duration in seconds to keep renewing message locks. "
            "Should be longer than expected processing time."
        ),
    )

    default_upload_file_chunk_size: int = Field(
        default=1,
        description=(
            "Number of records to process in a single file chunk when uploading."
        ),
    )
    upload_file_chunk_size_override: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Override the default upload file chunk size. Keyed by file type."
        ),
    )

    default_download_file_chunk_size: Literal[1] = Field(
        default=1,
        description=(
            "Number of records to process in a single file chunk when downloading."
            "Not configurable or used, just representing that we stream line-by-line "
            "at this point."
        ),
    )

    presigned_url_expiry_seconds: int = Field(
        default=3600,
        description="The number of seconds a signed URL is valid for.",
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
        if self.running_locally:
            if self.minio_config:
                return "minio"
            if self.azure_blob_config:
                return "azure"
            if self.env == Environment.TEST:
                # If we reach here, we are in a test environment and haven't
                # specified a blob config, so assume it is mocked. Just return
                # minio to keep pydantic happy.
                return "minio"
        return "azure"

    @property
    def default_blob_container(self) -> str:
        """Return the default blob container."""
        if self.running_locally:
            if self.minio_config:
                return self.minio_config.bucket
            if self.azure_blob_config:
                return self.azure_blob_config.container
            if self.env == Environment.TEST:
                # If we reach here, we are in a test environment and haven't
                # specified a blob config, so assume it is mocked.
                return "test"
        if not self.azure_blob_config:
            msg = "Azure Blob Storage configuration is not given."
            raise ValueError(msg)
        return self.azure_blob_config.container


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
