"""Containers setup for end-to-end tests."""

import json
import logging
import os
import pathlib
import uuid

import httpx
import pytest
import testcontainers.elasticsearch
import testcontainers.rabbitmq
from alembic.command import upgrade
from elasticsearch import AsyncElasticsearch
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.core.container import DockerContainer
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.wait_strategies import HttpWaitStrategy, LogMessageWaitStrategy
from testcontainers.elasticsearch import ElasticSearchContainer
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.rabbitmq import RabbitMqContainer

from app.core.config import DatabaseConfig
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.robots.models.models import Robot
from app.persistence.sql.session import (
    AsyncDatabaseSessionManager,
    db_manager,
)
from tests.db_utils import alembic_config_from_url, clean_tables
from tests.es_utils import clean_test_indices, create_test_indices, delete_test_indices
from tests.factories import ReferenceFactory, RobotFactory

#####################
# Dirty fiddly bits #
#####################
# Monkeypatch testcontainers.elasticsearch._environment_by_version for elastic v9
testcontainers.elasticsearch._environment_by_version = lambda _: {  # noqa: SLF001
    "xpack.security.enabled": "false"
}

# Monkeypatch testcontainers.rabbitmq.RabbitMqContainer.readiness_probe to a no-op
testcontainers.rabbitmq.RabbitMqContainer.readiness_probe = lambda self: self


# Pass --log-cli-level info to see these
logger = logging.getLogger(__name__)

_cwd = pathlib.Path.cwd()
logger.info("Current working directory: %s", _cwd)

app_port = 8000
bucket_name = "test"
host_name = os.getenv("DOCKER_HOSTNAME", "host.docker.internal")
container_prefix = "e2e"


def print_logs(name: str, container: DockerContainer):
    """Print the logs of a container."""
    # This is relatively unwieldy. Future debuggers may find it useful
    # to pipe to files or honeycomb, depending on the size of the tests.
    logger.info(
        "%s logs:\n%s",
        name,
        container._container.logs().decode("utf-8"),  # noqa: SLF001
    )


###########################
# Infrastructure Fixtures #
###########################


@pytest.fixture(scope="session")
def minio_proxy():
    """
    Yield a simple proxy container for MinIO signed URLs.

    MinIO signed URLs are signed with the connection URL.
    App->MinIO uses `host_name` connection URL.
    Tests cannot access `host_name` (without special hosts.etc configuration).
    This tiny proxy container fetches the signed URL and serves it on localhost.
    Uses only Python standard library.
    """
    proxy_script_path = str(_cwd / "tests/e2e/_minio_proxy.py")
    container = (
        DockerContainer("python:3.11-slim")
        .with_command(["python", "/proxy.py"])
        .with_volume_mapping(proxy_script_path, "/proxy.py")
        .with_exposed_ports(8080)
        .with_name(f"{container_prefix}-minio-proxy")
        .waiting_for(HttpWaitStrategy(port=8080, path="/health"))
    )
    with container as proxy:
        yield proxy


@pytest.fixture(scope="session")
async def minio_proxy_client(minio_proxy: DockerContainer):
    """Yield a client for the minio proxy."""
    host = minio_proxy.get_container_host_ip()
    port = minio_proxy.get_exposed_port(8080)
    url = f"http://{host}:{port}/proxy"
    logger.info("Creating httpx client for MinIO proxy at %s", url)
    async with httpx.AsyncClient(base_url=url) as client:
        yield client


@pytest.fixture(scope="session")
def postgres():
    """Postgres container with alembic migrations applied."""
    logger.info("Creating Postgres container...")
    with PostgresContainer("postgres:17", driver="asyncpg").with_name(
        f"{container_prefix}-postgres"
    ) as postgres:
        logger.info("Applying alembic migrations.")
        alembic_config = alembic_config_from_url(postgres.get_connection_url())
        upgrade(alembic_config, "head")
        logger.info("Postgres container ready.")
        yield postgres


@pytest.fixture(scope="session")
async def pg_sessionmanager(
    postgres: PostgresContainer,
):
    """Build shared session manager for tests."""
    db_manager.init(DatabaseConfig(db_url=postgres.get_connection_url()), "test")
    # can add another init (redis, etc...)
    yield db_manager
    await db_manager.close()


@pytest.fixture
async def pg_session(pg_sessionmanager: AsyncDatabaseSessionManager):
    """Postgres session for use in tests."""
    engine = pg_sessionmanager._engine  # noqa: SLF001
    assert engine

    async with pg_sessionmanager.session() as session:
        yield session


@pytest.fixture(autouse=True)
async def pg_lifecycle(pg_sessionmanager: AsyncDatabaseSessionManager):
    """Cleanup database tables after each test."""
    # Alembic manages the schema with a session scope,
    # so we just need to clean the tables after each test
    yield

    engine = pg_sessionmanager._engine  # noqa: SLF001
    assert engine

    async with engine.begin() as conn:
        await clean_tables(conn)


@pytest.fixture(scope="session")
async def elasticsearch():
    """Elasticsearch container with default credentials."""
    logger.info("Creating Elasticsearch container...")
    with ElasticSearchContainer(
        "elasticsearch:9.1.4",
        # If elasticsearch is failing to start, check the container logs. Exit code 137
        # means out of memory. Annoyingly, this either means:
        # - Docker daemon doesn't have enough memory allocated (mem_limit is too high)
        # - Elasticsearch doesn't have enough memory allocated (mem_limit is too low)
        # Fun!
        mem_limit="2g",
    ).with_name(f"{container_prefix}-elasticsearch") as elasticsearch:
        logger.info("Creating Elasticsearch indices...")
        async with AsyncElasticsearch(elasticsearch.get_url()) as client:
            await create_test_indices(client)
        logger.info("Elasticsearch container ready.")
        yield elasticsearch
        async with AsyncElasticsearch(elasticsearch.get_url()) as client:
            await delete_test_indices(client)


@pytest.fixture
async def es_client(elasticsearch: ElasticSearchContainer):
    """Elasticsearch client for use in tests."""
    async with AsyncElasticsearch(elasticsearch.get_url()) as client:
        yield client


@pytest.fixture(autouse=True)
async def es_lifecycle(elasticsearch: ElasticSearchContainer):
    """Clean indices around each test."""
    # Indices are created with session scope,
    # so we just need to clean them after each test
    yield
    async with AsyncElasticsearch(elasticsearch.get_url()) as client:
        await clean_test_indices(client)


@pytest.fixture(scope="session")
def minio():
    """MinIO container with default credentials."""
    logger.info("Starting MinIO container...")
    with MinioContainer("minio/minio").with_name(f"{container_prefix}-minio") as minio:
        logger.info("MinIO container ready.")
        yield minio


@pytest.fixture(autouse=True)
def minio_lifecycle(minio: MinioContainer):
    """Clean buckets around each test."""
    config = minio.get_config()
    client = Minio(
        endpoint=config["endpoint"],
        access_key=config["access_key"],
        secret_key=config["secret_key"],
        secure=False,
    )
    client.make_bucket(bucket_name)
    yield
    for obj in client.list_objects(bucket_name, recursive=True):
        client.remove_object(bucket_name, obj.object_name)
    client.remove_bucket(bucket_name)


@pytest.fixture(scope="session")
def rabbitmq():
    """RabbitMQ container."""
    logger.info("Creating RabbitMQ container...")
    with (
        RabbitMqContainer("rabbitmq:3-management", port=5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
        .with_name(f"{container_prefix}-rabbitmq") as rabbitmq
    ):
        logger.info("RabbitMQ container ready.")
        yield rabbitmq


@pytest.fixture(scope="session")
async def destiny_repository_image(request: pytest.FixtureRequest) -> str:
    """Get the destiny-repository container."""
    if request.config.getoption("--build"):
        logger.info("Building destiny-repository image...")
        DockerClient().build(".", dockerfile="Dockerfile.e2e", tag="destiny-repository")
        logger.info("destiny-repository image built.")

    return "destiny-repository"


def _add_env(
    container: DockerContainer,
    postgres: PostgresContainer,
    elasticsearch: ElasticSearchContainer,
    rabbitmq: RabbitMqContainer,
    minio: MinioContainer,
) -> DockerContainer:
    """Add environment variables to a container."""
    minio_config = minio.get_config()
    return (
        container.with_env(
            "MESSAGE_BROKER_URL",
            f"amqp://guest:guest@{(
                rabbitmq.get_container_host_ip()
                .replace('localhost', host_name)
            )}:{rabbitmq.get_exposed_port(5672)}/",
        )
        .with_env(
            "DB_CONFIG",
            json.dumps(
                {
                    "DB_URL": postgres.get_connection_url().replace(
                        "localhost", host_name
                    )
                }
            ),
        )
        .with_env(
            "MINIO_CONFIG",
            json.dumps(
                {
                    "HOST": minio_config["endpoint"].replace("localhost", host_name),
                    "ACCESS_KEY": minio_config["access_key"],
                    "SECRET_KEY": minio_config["secret_key"],
                    "BUCKET": bucket_name,
                }
            ),
        )
        .with_env(
            "ES_CONFIG",
            json.dumps(
                {
                    "ES_INSECURE_URL": elasticsearch.get_url().replace(
                        "localhost", host_name
                    )
                }
            ),
        )
        .with_env("FEATURE_FLAGS", json.dumps({"deduplication": True}))
        .with_env("ENV", "test")
        .with_env("TESTS_USE_RABBITMQ", "true")
        .with_env("AZURE_APPLICATION_ID", "dummy")
        .with_env("AZURE_TENANT_ID", "dummy")
    )


@pytest.fixture(scope="session")
async def worker(
    postgres: PostgresContainer,
    elasticsearch: ElasticSearchContainer,
    rabbitmq: RabbitMqContainer,
    minio: MinioContainer,
    destiny_repository_image: str,
):
    """Get the worker container."""
    logger.info("Starting worker container...")
    worker = (
        _add_env(
            DockerContainer(destiny_repository_image),
            postgres,
            elasticsearch,
            rabbitmq,
            minio,
        )
        .with_name(f"{container_prefix}-worker")
        .with_command(
            [
                "uv",
                "run",
                "taskiq",
                "worker",
                "app.tasks:broker",
                "--tasks-pattern",
                "app/**/tasks.py",
                "--fs-discover",
            ]
        )
        .with_env("APP_NAME", "destiny-worker")
        .with_volume_mapping(str(_cwd / "app"), "/app/app")
        .with_volume_mapping(str(_cwd / "libs/sdk"), "/app/libs/sdk")
        .waiting_for(LogMessageWaitStrategy("Listening started."))
    )
    with worker as container:
        logger.info("Worker container ready.")
        try:
            yield container
        finally:
            print_logs("Worker", container)


@pytest.fixture(scope="session")
async def app(  # noqa: PLR0913
    postgres: PostgresContainer,
    elasticsearch: ElasticSearchContainer,
    rabbitmq: RabbitMqContainer,
    minio: MinioContainer,
    destiny_repository_image: str,
    worker: DockerContainer,  # noqa: ARG001, used for ordering dependencies
):
    """Get the main application container."""
    logger.info("Starting app container...")
    app = (
        _add_env(
            DockerContainer(destiny_repository_image),
            postgres,
            elasticsearch,
            rabbitmq,
            minio,
        )
        .with_env("APP_NAME", "destiny-app")
        .with_name(f"{container_prefix}-app")
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
            ]
        )
        .with_volume_mapping(str(_cwd / "app"), "/app/app")
        .with_volume_mapping(str(_cwd / "libs/sdk"), "/app/libs/sdk")
        .waiting_for(
            HttpWaitStrategy(
                port=app_port, path="/v1/system/healthcheck/?azure_blob_storage=false"
            ).for_status_code(200)
        )
    )
    with app as container:
        logger.info("App container ready.")
        try:
            yield container
        finally:
            print_logs("App", container)


@pytest.fixture(scope="session")
async def destiny_client_v1(app: DockerContainer) -> httpx.AsyncClient:
    """Get a httpx client for the main application."""
    host = app.get_container_host_ip()
    port = app.get_exposed_port(app_port)
    url = f"http://{host}:{port}/v1/"
    logger.info("Creating httpx client for %s", url)
    return httpx.AsyncClient(base_url=url)


def pytest_addoption(parser: pytest.Parser):
    """Add custom command line options to pytest."""
    parser.addoption(
        "--build",
        action="store_true",
        default=False,
        help="Rebuild the destiny image. Helps when uv dependencies have changed. "
        "Code changes will be picked up automatically without needing this flag.",
    )


#################
# Data Fixtures #
#################


@pytest.fixture
async def robot(destiny_client_v1: httpx.AsyncClient) -> Robot:
    """Create a robot."""
    robot: Robot = RobotFactory.build()
    response = await destiny_client_v1.post(
        "/robots/",
        json={
            "name": robot.name,
            "description": robot.description,
            "base_url": str(robot.base_url),
            "owner": robot.owner,
        },
    )
    assert response.status_code == 201
    data = response.json()
    return Robot(**data)


@pytest.fixture
async def add_references(pg_session: AsyncSession):
    """Create some references."""

    async def _make(n: int) -> set[uuid.UUID]:
        references = [ReferenceFactory.build() for _ in range(n)]
        for reference in references:
            sql_reference = SQLReference.from_domain(reference)
            pg_session.add(sql_reference)
        await pg_session.commit()
        return {reference.id for reference in references}

    return _make
