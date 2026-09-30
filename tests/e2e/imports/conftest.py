"""Fixtures for e2e import tests."""

import datetime
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid7

import httpx
import pytest
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
from destiny_sdk.enhancements import EnhancementFileInput
from destiny_sdk.identifiers import OpenAlexIdentifier
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from testcontainers.azurite import AzuriteContainer

from app.domain.robots.models.models import Robot
from tests.e2e.conftest import (
    azurite_account_key,
    azurite_account_name,
    blob_container_name,
    get_azurite_account_url,
    host_name,
)
from tests.e2e.utils import refresh_robot_automation_index
from tests.factories import ReferenceFactory

if TYPE_CHECKING:
    from app.domain.references.models.models import Reference


@pytest.fixture
def generate_sdk_reference_file_inputs() -> Callable[[int], list[ReferenceFileInput]]:
    """Get a random ReferenceFileInput."""

    def _make(n: int) -> list[ReferenceFileInput]:
        assert n > 0, "n must be greater than 0"
        references: list[Reference] = ReferenceFactory.build_batch(n)
        return [
            ReferenceFileInput(
                visibility=r.visibility,
                enhancements=[
                    EnhancementFileInput(**e.model_dump()) for e in r.enhancements or []
                ],
                # Avoid accidental identifier candidates between unrelated records.
                identifiers=[OpenAlexIdentifier(identifier=f"W{uuid7().int}")],
            )
            for r in references
        ]

    return _make


@pytest.fixture
def get_import_file_signed_url(azurite: AzuriteContainer):
    """Upload ReferenceFileInput as a JSONL blob and yield a signed download URL."""
    service_client = BlobServiceClient.from_connection_string(
        azurite.get_connection_string()
    )

    @asynccontextmanager
    async def _upload(
        sdk_reference_file_input: list[ReferenceFileInput],
    ) -> AsyncIterator[str]:
        """Upload and yield a signed URL."""
        assert len(sdk_reference_file_input) > 0, "Must provide at least one reference"
        content = "\n".join(r.to_jsonl() for r in sdk_reference_file_input).encode(
            "utf-8"
        )
        blob_name = f"imports/{uuid7()}.jsonl"
        blob_client = service_client.get_blob_client(blob_container_name, blob_name)
        blob_client.upload_blob(content)
        sas_token = generate_blob_sas(
            account_name=azurite_account_name,
            container_name=blob_container_name,
            blob_name=blob_name,
            account_key=azurite_account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        )
        account_url = get_azurite_account_url(azurite, host_name)

        try:
            yield f"{account_url}/{blob_container_name}/{blob_name}?{sas_token}"
        finally:
            blob_client.delete_blob()

    return _upload


@pytest.fixture
async def robot_automation_on_all_imports(
    destiny_client_v1: httpx.AsyncClient, es_client: AsyncElasticsearch, robot: Robot
) -> UUID:
    """Create a robot automation that runs on all imports."""
    response = await destiny_client_v1.post(
        "/enhancement-requests/automations/",
        json={
            "robot_id": str(robot.id),
            "query": {"match_all": {}},
        },
    )
    assert response.status_code == 201
    await refresh_robot_automation_index(es_client)
    return robot.id
