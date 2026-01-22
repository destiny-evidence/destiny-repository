"""API config parsing and model."""

import datetime
import tomllib
from enum import StrEnum, auto
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    Field,
    FilePath,
    HttpUrl,
    PostgresDsn,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import ExternalIdentifierType
from app.utils.time_and_date import iso8601_duration_adapter

logger = get_logger(__name__)


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


class ESConfig(BaseModel):
    """Elasticsearch configuration."""

    # Traditional authentication (for local development)
    es_url: HttpUrl | list[HttpUrl] | None = Field(
        default=None,
        description="If a list, connections will be created to all nodes in the list.",
    )
    es_user: str | None = None
    es_pass: str | None = None
    es_ca_path: FilePath | None = None

    es_insecure_url: HttpUrl | None = Field(
        default=None,
        description=(
            "For connecting to insecure Elasticsearch instances when testing."
        ),
    )
    # API key authentication (for production)
    cloud_id: str | None = None
    api_key: str | None = None

    # Other configuration
    timeout_seconds: int = 30
    retry_on_timeout: bool = True
    max_retries: int = 5

    @property
    def uses_api_key(self) -> bool:
        """Return True if using API key authentication."""
        return self.cloud_id is not None and self.api_key is not None

    @property
    def es_hosts(self) -> list[str]:
        """Return the Elasticsearch host(s) as a list of strings."""
        if self.uses_api_key or self.es_url is None:
            msg = "Elasticsearch URL is not provided."
            raise ValueError(msg)
        return [
            str(url)
            for url in (self.es_url if isinstance(self.es_url, list) else [self.es_url])
        ]

    @model_validator(mode="after")
    def validate_authentication(self) -> Self:
        """Validate the Elasticsearch authentication method."""
        has_api_key = all([self.cloud_id, self.api_key])
        has_user_pass = any((self.es_url, self.es_user, self.es_pass, self.es_ca_path))

        # count how many auth methods are provided
        auth_methods = sum(
            [
                has_api_key,
                has_user_pass,
                bool(self.es_insecure_url),
            ]
        )

        if auth_methods != 1:
            msg = (
                "Exactly one of the following authentication methods must be provided: "
                "API key (cloud_id, api_key), traditional auth (es_url, es_user, "
                "es_pass, es_ca_path), or insecure URL (es_insecure_url)."
            )
            raise ValueError(msg)

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


class LogLevel(StrEnum):
    """Log level enum."""

    NOTSET = auto()
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


optimistic_fraction = Field(default=1.0, ge=0.0, le=1.0)
pessimistic_fraction = Field(default=0.0, ge=0.0, le=1.0)


class LogSamplingConfig(BaseModel):
    """Log level sampling configuration."""

    notset_sample_rate: float = pessimistic_fraction
    debug_sample_rate: float = pessimistic_fraction
    info_sample_rate: float = optimistic_fraction
    warning_sample_rate: float = optimistic_fraction
    error_sample_rate: float = optimistic_fraction
    critical_sample_rate: float = optimistic_fraction

    def get_rate(self, level: LogLevel | str) -> float:
        """Get the sample rate for a given log level."""
        if isinstance(level, str):
            try:
                level = LogLevel[level.upper()]
            except KeyError:
                return 1.0
        return self.rates.get(level, 1.0)

    @property
    def rates(self) -> dict[LogLevel, float]:
        """Get a mapping of log levels to their sample rates."""
        return {
            LogLevel.NOTSET: self.notset_sample_rate,
            LogLevel.DEBUG: self.debug_sample_rate,
            LogLevel.INFO: self.info_sample_rate,
            LogLevel.WARNING: self.warning_sample_rate,
            LogLevel.ERROR: self.error_sample_rate,
            LogLevel.CRITICAL: self.critical_sample_rate,
        }


class OTelConfig(BaseModel):
    """OpenTelemetry configuration."""

    trace_endpoint: HttpUrl
    meter_endpoint: HttpUrl
    log_endpoint: HttpUrl
    api_key: str | None = None

    timeout: int = 30

    # Flags to control low-level automatic instrumentation
    instrument_sql: bool = False

    log_sample_config: LogSamplingConfig = Field(
        default=LogSamplingConfig(),
        description="Log level sampling configuration. "
        "This applies only to OpenTelemetry logs.",
    )


class Environment(StrEnum):
    """Environment enum."""

    PRODUCTION = auto()
    STAGING = auto()
    DEVELOPMENT = auto()
    LOCAL = auto()
    TEST = auto()

    @classmethod
    def local_envs(cls) -> set["Environment"]:
        """Get environment values that are for local development."""
        return {cls.LOCAL, cls.TEST}


class ESIndexingOperation(StrEnum):
    """Enum for Elasticsearch indexing operations."""

    REFERENCE_IMPORT = auto()


class ESPercolationOperation(StrEnum):
    """Enum for Elasticsearch percolation operations."""

    ROBOT_AUTOMATION = auto()


class UploadFile(StrEnum):
    """Enum for upload file types."""

    ENHANCEMENT_REQUEST_REFERENCE_DATA = auto()
    ROBOT_ENHANCEMENT_REFERENCE_DATA = auto()


class TOML(BaseModel):
    """Information extracted from a pyproject.toml file."""

    toml_path: Path = Field(
        description=(
            "Path to the directroy where the pyproject.toml file"
            "is located from the settings file."
        )
    )

    @property
    def pyproject_toml(self) -> dict[str, Any]:
        """Get the contents of pyproject.toml."""
        return tomllib.load((self.toml_path / "pyproject.toml").open("rb"))

    @property
    def app_version(self) -> str:
        """Get the application version from pyproject.toml."""
        return self.pyproject_toml["project"]["version"]


class FeatureFlags(BaseModel):
    """Feature flags for the application."""


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    project_root: Path = Path(__file__).joinpath("../../..").resolve()
    toml: TOML = TOML(toml_path=project_root)

    feature_flags: FeatureFlags = FeatureFlags()

    db_config: DatabaseConfig
    es_config: ESConfig
    minio_config: MinioConfig | None = None
    azure_blob_config: AzureBlobConfig | None = None
    otel_config: OTelConfig | None = None
    otel_enabled: bool = False

    azure_application_id: str
    azure_login_url: str
    message_broker_url: str | None = None
    message_broker_namespace: str | None = None
    message_broker_queue_name: str = "taskiq"
    cli_client_id: str | None = None
    app_name: str

    max_pending_enhancements_batch_size: int = Field(
        default=10000,
        description=(
            "Maximum number of pending enhancements to return in a single batch."
        ),
    )

    max_lookup_reference_query_length: int = Field(
        default=100,
        description=(
            "Maximum number of identifiers to allow in a single reference lookup query."
        ),
    )

    default_es_indexing_chunk_size: int = Field(
        default=1000,
        description=(
            "Number of records to process in a single chunk when indexing to "
            "Elasticsearch."
        ),
    )
    es_indexing_chunk_size_override: dict[ESIndexingOperation, int] = Field(
        default_factory=dict,
        description=("Override the default Elasticsearch indexing chunk size."),
    )

    default_es_percolation_chunk_size: int = Field(
        default=1000,
        description=(
            "Number of records to process in a single chunk when percolating to "
            "Elasticsearch."
        ),
    )
    es_percolation_chunk_size_override: dict[ESPercolationOperation, int] = Field(
        default_factory=dict,
        description=("Override the default Elasticsearch percolation chunk size."),
    )

    import_reference_retry_count: int = Field(
        default=3,
        description=(
            "Number of times to retry importing a reference before marking it as "
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
    upload_file_chunk_size_override: dict[UploadFile, int] = Field(
        default_factory=dict,
        description=("Override the default upload file chunk size."),
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

    default_pending_enhancement_lease_duration: datetime.timedelta = Field(
        default=iso8601_duration_adapter.validate_python("PT10M"),
        description=(
            "The default duration to lease pending enhancements for, provided "
            "in ISO 8601 duration format eg 'PT10M'."
        ),
    )

    env: Environment = Field(
        default=Environment.PRODUCTION,
        description="The environment the app is running in.",
    )

    tests_use_rabbitmq: bool = Field(
        default=False,
        description=(
            "Whether to use RabbitMQ for tests. Only used in test environment. "
            "If false, uses in-memory broker."
        ),
    )

    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="The log level for the application. "
        "This applies to both opentelemetry and standard logging.",
    )

    cors_allow_origins: list[str] = Field(
        default_factory=list,
        description="List of allowed origins for CORS.",
    )

    trusted_unique_identifier_types: set[ExternalIdentifierType] = Field(
        default_factory=set,
        description=(
            "Set of external identifier types that are considered trusted unique "
            "identifiers for references. These are used to shortcut deduplication. "
            "If empty, shortcutting is essentially feature-flagged off."
        ),
    )

    @property
    def running_locally(self) -> bool:
        """Return True if the app is running locally."""
        return self.env in Environment.local_envs()

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

    @property
    def trace_repr(self) -> str:
        """Get a string representation of the config for tracing."""
        return (
            f"feature_flags={self.feature_flags.model_dump_json()},"
            "trusted_unique_identifier_types="
            f"{[t.value for t in self.trusted_unique_identifier_types]}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
