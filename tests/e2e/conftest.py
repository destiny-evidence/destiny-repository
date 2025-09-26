"""Containers setup for end-to-end tests."""

# TODO List:
# - [x] Analyze requirements
# - [ ] Refactor to use dynamic container URLs/configs
# - [ ] Implement proper waiting strategies (no fixed sleeps)
# - [ ] Standardize versions/configs from environment or central config
# - [ ] Improve error handling/logging
# - [ ] Externalize sensitive configs
# - [ ] Test and verify improved setup

import json
import os
import subprocess
import time

import httpx
import pytest
import asyncpg
from testcontainers.core.container import DockerContainer
from testcontainers.elasticsearch import ElasticSearchContainer
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.rabbitmq import RabbitMqContainer
from elasticsearch import AsyncElasticsearch


@pytest.fixture(scope="module")
async def postgres():
    """Postgres container with alembic migrations applied."""
    with PostgresContainer("postgres:17") as postgres:
        subprocess.run(  # noqa: S603
            [
                "/usr/bin/uv",
                "run",
                "alembic",
                "upgrade",
                "head",
            ],
            check=True,
        )
        yield postgres
    postgres.stop()


@pytest.fixture(scope="session")
async def pg_session(postgres: PostgresContainer):
    """Postgres session for use in tests."""
    url = postgres.get_connection_url()
    async with asyncpg.connect(url) as connection:
        yield connection


@pytest.fixture(scope="session")
async def elasticsearch():
    """Elasticsearch container with default credentials."""
    with ElasticSearchContainer("elasticsearch:9.0.0") as elastic:
        yield elastic


@pytest.fixture(scope="session")
async def es_client(elasticsearch: ElasticSearchContainer):
    """Elasticsearch client for use in tests."""
    host = elasticsearch.get_container_host_ip()
    port = elasticsearch.get_exposed_port(9200)
    async with AsyncElasticsearch(
        f"http://{host}:{port}", basic_auth=("elastic", "changeme")
    ) as client:
        yield client


@pytest.fixture(scope="session")
async def minio():
    """MinIO container with default credentials."""
    with MinioContainer("minio/minio") as minio:
        yield minio


@pytest.fixture(scope="session")
async def rabbitmq():
    """RabbitMQ container."""
    with RabbitMqContainer("rabbitmq:3-management") as rabbit:
        yield rabbit


@pytest.fixture(scope="session")
def app(
    postgres: PostgresContainer,
    elasticsearch: ElasticSearchContainer,
    minio: MinioContainer,
    rabbitmq: RabbitMqContainer,
):
    """Get the main application container."""
    minio_config = minio.get_config()
    es_config = elasticsearch.get()
    app = (
        DockerContainer("destiny-app:latest")
        .with_exposed_ports(8000)
        .with_env("MESSAGE_BROKER_URL", rabbitmq.get_container_host_ip())
        .with_env("DB_CONFIG", json.dumps({"DB_URL": postgres.get_connection_url()}))
        .with_env(
            "MINIO_CONFIG",
            json.dumps(
                {
                    "HOST": minio_config["endpoint"],
                    "ACCESS_KEY": minio_config["access_key"],
                    "SECRET_KEY": minio_config["secret_key"],
                }
            ),
        )
        .with_env(
            "ES_CONFIG",
            json.dumps(
                {
                    "ES_URL": es_url,
                    "ES_USER": es_user,
                    "ES_PASS": es_pass,
                    "ES_CA_PATH": es_ca_path,
                }
            ),
        )
        .with_env("APP_NAME", "destiny-app")
        .with_command("fastapi dev app/main.py --host 0.0.0.0 --port 8000")
        .with_volume_mapping("./app", "/app/app")
        .with_volume_mapping("./libs/sdk", "/app/libs/sdk")
        .with_volume_mapping("certs", "/app/certs")
    )
    with app as container:
        host = container.get_host_ip()
        port = container.get_exposed_port(8000)
        os.environ["REPO_URL"] = f"http://{host}:{port}/v1"
        # Wait for healthcheck
        for _ in range(30):
            try:
                r = httpx.get(f"http://{host}:{port}/v1/system/health")
                if r.status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        yield container


@pytest.fixture(scope="session")
def worker(postgres, elasticsearch, minio, rabbitmq):
    """Get the worker container."""
    # Use dynamic URLs/configs from testcontainers
    worker_db_url = os.environ["DB_URL"]
    minio_url = os.environ["MINIO_URL"]
    minio_access_key = os.environ["MINIO_ROOT_USER"]
    minio_secret_key = os.environ["MINIO_ROOT_PASSWORD"]
    es_url = os.environ["ES_URL"]
    es_user = os.environ["ES_USER"]
    es_pass = os.environ["ES_PASS"]
    es_ca_path = os.environ.get("ES_CA_PATH", "/app/certs/ca/ca.crt")
    message_broker_url = os.environ["MESSAGE_BROKER_URL"]

    worker = (
        DockerContainer("destiny-app:latest")
        .with_env("MESSAGE_BROKER_URL", message_broker_url)
        .with_env("DB_CONFIG", json.dumps({"DB_URL": worker_db_url}))
        .with_env(
            "MINIO_CONFIG",
            json.dumps(
                {
                    "HOST": minio_url.replace("http://", "").replace("https://", ""),
                    "ACCESS_KEY": minio_access_key,
                    "SECRET_KEY": minio_secret_key,
                }
            ),
        )
        .with_env(
            "ES_CONFIG",
            json.dumps(
                {
                    "ES_URL": es_url,
                    "ES_USER": es_user,
                    "ES_PASS": es_pass,
                    "ES_CA_PATH": es_ca_path,
                }
            ),
        )
        .with_env("APP_NAME", "destiny-worker")
        .with_command(
            "taskiq worker app.tasks:broker --tasks-pattern app/**/tasks.py --fs-discover --reload"
        )
        .with_volume_mapping("./app", "/app/app")
        .with_volume_mapping("./libs/sdk", "/app/libs/sdk")
        .with_volume_mapping("certs", "/app/certs")
    )
    with worker as container:
        yield container


@pytest.fixture(scope="session", autouse=True)
def setup_infrastructure(  # noqa: PLR0913
    request: pytest.FixtureRequest,
) -> None:
    """Create and destroy infrastructure for end-to-end tests."""
    postgres = _start_postgres_container()
    postgres.start()
    # elasticsearch.start()
    # minio.start()
    # rabbitmq.start()
    # app.start()
    # worker.start()

    # def cleanup() -> None:
    #     postgres.stop()
    #     elasticsearch.stop()
    #     minio.stop()
    #     rabbitmq.stop()
    #     app.stop()
    #     worker.stop()

    request.addfinalizer(cleanup)  # noqa: PT021, explicitly recommended in testcontainers docs
