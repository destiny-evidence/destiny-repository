"""Keycloak e2e test fixtures."""

import asyncio
import pathlib

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import (
    CompositeWaitStrategy,
    HttpWaitStrategy,
    LogMessageWaitStrategy,
)
from testcontainers.elasticsearch import ElasticSearchContainer
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.rabbitmq import RabbitMqContainer

from app.core.telemetry.logger import get_logger
from tests.e2e.conftest import _add_env

logger = get_logger(__name__)

_cwd = pathlib.Path.cwd()
container_prefix = "e2e"
host_name = "host.docker.internal"


@pytest.fixture(scope="session")
def keycloak():
    """Start a Keycloak container with test realm."""
    logger.info("Starting Keycloak container...")

    # Use dedicated import directory with test realm config
    import_dir = str(_cwd / "tests/e2e/auth/keycloak-import")

    container = (
        DockerContainer("quay.io/keycloak/keycloak:26.0")
        .with_name(f"{container_prefix}-keycloak")
        .with_exposed_ports(8080)
        .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
        .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin")
        .with_env("KC_HOSTNAME_STRICT", "false")
        .with_env("KC_HTTP_ENABLED", "true")
        .with_volume_mapping(import_dir, "/opt/keycloak/data/import")
        .with_command("start-dev --import-realm")
        # Wait for realm import to complete (this log message appears after import)
        .waiting_for(LogMessageWaitStrategy("Realm 'destiny' imported"))
    )

    with container as keycloak:
        logger.info("Keycloak container ready.")
        yield keycloak


@pytest.fixture(scope="session")
def keycloak_url(keycloak: DockerContainer) -> str:
    """Get the Keycloak URL for external access."""
    host = keycloak.get_container_host_ip()
    port = keycloak.get_exposed_port(8080)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def keycloak_internal_url(keycloak: DockerContainer) -> str:
    """Get the Keycloak URL for container-to-container access."""
    port = keycloak.get_exposed_port(8080)
    return f"http://{host_name}:{port}"


async def _get_keycloak_token(keycloak_url: str, scopes: str) -> str:
    """
    Get a token from Keycloak with retry logic.

    Args:
        keycloak_url: Base URL for Keycloak (e.g., http://localhost:8080)
        scopes: Space-separated list of scopes to request

    Returns:
        The access token string

    """
    token_url = f"{keycloak_url}/realms/destiny/protocol/openid-connect/token"
    max_retries = 30
    retry_delay = 1.0

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                response = await client.post(
                    token_url,
                    data={
                        "grant_type": "password",
                        "client_id": "destiny-auth-client",
                        "username": "testuser",
                        "password": "testpass",
                        "scope": scopes,
                    },
                    timeout=5.0,
                )
                if response.status_code == 200:
                    return response.json()["access_token"]

                if response.status_code == 400 and "invalid_scope" in response.text:
                    logger.info(
                        "Keycloak realm not ready yet (attempt %d/%d): %s",
                        attempt + 1,
                        max_retries,
                        response.text,
                    )
                    await asyncio.sleep(retry_delay)
                    continue

                logger.error(
                    "Failed to get token from Keycloak: %s %s",
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()
            except httpx.RequestError as e:
                logger.info(
                    "Keycloak not accepting connections (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    str(e),
                )
                await asyncio.sleep(retry_delay)
                continue

    msg = f"Failed to get token from Keycloak after {max_retries} attempts"
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
async def keycloak_token(keycloak_url: str) -> str:
    """Get a token from Keycloak with reference.reader.all scope."""
    return await _get_keycloak_token(keycloak_url, "openid reference.reader.all")


@pytest.fixture(scope="session")
async def keycloak_token_all_scopes(keycloak_url: str) -> str:
    """Get a token from Keycloak with all available scopes."""
    return await _get_keycloak_token(
        keycloak_url,
        "openid reference.reader.all administrator.all import.writer.all "
        "reference.deduplicator.all enhancement_request.writer.all robot.writer.all",
    )


def add_keycloak_env(
    container: DockerContainer,
    keycloak: DockerContainer,
) -> DockerContainer:
    """Add Keycloak environment variables to a container."""
    port = keycloak.get_exposed_port(8080)
    # Use host.docker.internal for JWKS fetching (from inside the container)
    keycloak_internal = f"http://{host_name}:{port}"
    # Use localhost for issuer validation (tokens are obtained from localhost by tests)
    keycloak_external = f"http://localhost:{port}"

    return (
        container.with_env("AUTH_PROVIDER", "keycloak")
        .with_env("KEYCLOAK_URL", keycloak_internal)
        .with_env("KEYCLOAK_ISSUER_URL", keycloak_external)
        .with_env("KEYCLOAK_REALM", "destiny")
        .with_env("KEYCLOAK_CLIENT_ID", "destiny-repository-client")
    )


app_port = 8000


@pytest.fixture(scope="module")
def keycloak_app(  # noqa: PLR0913
    postgres: PostgresContainer,
    elasticsearch: ElasticSearchContainer,
    rabbitmq: RabbitMqContainer,
    minio: MinioContainer,
    destiny_repository_image: str,
    keycloak: DockerContainer,
):
    """Get the main application container configured for Keycloak auth."""
    logger.info("Starting app container with Keycloak auth...")
    app = (
        _add_env(
            DockerContainer(destiny_repository_image),
            postgres,
            elasticsearch,
            rabbitmq,
            minio,
        )
        .with_env("APP_NAME", "destiny-app-keycloak")
        .with_env("BYPASS_AUTH", "false")  # Enforce auth for Keycloak testing
        .with_name(f"{container_prefix}-keycloak-app")
        .with_exposed_ports(app_port)
        .with_command(
            [
                "uv",
                "run",
                "fastapi",
                "dev",
                "app/main.py",
                "--host",
                "0.0.0.0",  # noqa: S104
                "--port",
                str(app_port),
            ],
        )
        .with_volume_mapping(str(_cwd / "app"), "/app/app")
        .with_volume_mapping(str(_cwd / "libs/sdk"), "/app/libs/sdk")
        .waiting_for(
            CompositeWaitStrategy(
                LogMessageWaitStrategy("Uvicorn running on http://0.0.0.0:8000"),
                HttpWaitStrategy(
                    port=app_port,
                    path="/v1/system/healthcheck/?azure_blob_storage=false",
                ).for_status_code(200),
            ),
        )
    )
    # Add Keycloak environment variables
    app = add_keycloak_env(app, keycloak)

    with app as container:
        logger.info("App container with Keycloak ready.")
        yield container


@pytest.fixture
async def keycloak_api_client(keycloak_app: DockerContainer) -> httpx.AsyncClient:
    """Get an httpx client for the Keycloak-enabled app."""
    host = keycloak_app.get_container_host_ip()
    port = keycloak_app.get_exposed_port(app_port)
    url = f"http://{host}:{port}/v1/"
    logger.info("Creating httpx client for Keycloak app at %s", url)
    async with httpx.AsyncClient(base_url=url) as client:
        yield client
