"""Tests ES repair functionality (and inherently the link between SQL and ES)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.api.exception_handlers import not_found_exception_handler
from app.core.exceptions import NotFoundError
from app.domain.references import tasks as reference_tasks
from app.domain.references.models.models import Visibility
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    ExternalIdentifier as SQLExternalIdentifier,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.models.sql import (
    RobotAutomation as SQLRobotAutomation,
)
from app.domain.robots.models.sql import Robot as SQLRobot
from app.persistence.es.client import AsyncESClientManager
from app.persistence.es.index_manager import IndexManager
from app.system import routes as system_routes
from app.tasks import broker
from tests.factories import (
    AnnotationEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    PubMedIdentifierFactory,
)


async def wait_for_all_tasks() -> None:
    """Wait for all tasks to complete."""
    assert isinstance(broker, InMemoryBroker)
    # Gives time for chained tasks to be scheduled (eg repairing)
    await asyncio.sleep(0.5)
    await broker.wait_all()


async def sub_test_reference_index_initial_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    index_manager: IndexManager,
    reference_id: uuid.UUID,
) -> None:
    """Sub-test: Test reference index repair with rebuild=True."""
    index_name = index_manager.alias_name
    # Test repair with rebuild
    response = await client.post(
        f"/system/indices/{index_name}/repair/",
        params={"rebuild": True},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    await wait_for_all_tasks()

    # Verify index still exists after rebuild
    exists = await es_client.indices.exists(index=index_name)
    assert exists

    # Verify the data was indexed in Elasticsearch
    await es_client.indices.refresh(index=index_name)
    es_response = await es_client.search(
        index=index_name, body={"query": {"term": {"_id": str(reference_id)}}}
    )

    assert es_response["hits"]["total"]["value"] == 1
    es_doc = es_response["hits"]["hits"][0]["_source"]
    assert es_doc["visibility"] == "public"
    assert len(es_doc["identifiers"]) == 1
    assert es_doc["identifiers"][0]["identifier_type"] == "doi"
    assert es_doc["identifiers"][0]["identifier"] == "10.1234/test-reference"
    assert len(es_doc["enhancements"]) == 1
    assert es_doc["enhancements"][0]["source"] == "test_source"


async def sub_test_reference_index_update_without_rebuild(  # noqa: PLR0913
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
    index_manager: IndexManager,
    reference_id: uuid.UUID,
    reference: SQLReference,
) -> None:
    """Sub-test: Test reference index repair with rebuild=False after SQL update."""
    # Update SQL data - change visibility and add another identifier
    index_name = index_manager.alias_name
    reference.visibility = Visibility.RESTRICTED
    new_identifier = SQLExternalIdentifier.from_domain(
        LinkedExternalIdentifierFactory.build(
            reference_id=reference_id,
            identifier=PubMedIdentifierFactory.build(identifier=12345678),
        )
    )
    session.add(new_identifier)
    await session.commit()

    # Test repair without rebuild to update existing data
    response = await client.post(
        f"/system/indices/{index_name}/repair/",
        params={"rebuild": False},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    await wait_for_all_tasks()

    # Verify the updated data is reflected in Elasticsearch
    await es_client.indices.refresh(index=index_name)
    es_response = await es_client.search(
        index=index_name, body={"query": {"term": {"_id": str(reference_id)}}}
    )

    assert es_response["hits"]["total"]["value"] == 1
    es_doc = es_response["hits"]["hits"][0]["_source"]
    assert es_doc["visibility"] == "restricted"  # Updated visibility
    assert len(es_doc["identifiers"]) == 2  # Now has 2 identifiers
    # Check both identifiers are present
    identifier_types = {id_obj["identifier_type"] for id_obj in es_doc["identifiers"]}
    assert "doi" in identifier_types
    assert "pm_id" in identifier_types
    assert len(es_doc["enhancements"]) == 1
    assert es_doc["enhancements"][0]["source"] == "test_source"


async def sub_test_robot_automation_initial_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    index_manager: IndexManager,
    automation_id: uuid.UUID,
    robot_id: uuid.UUID,
) -> None:
    """Sub-test: Test robot automation index repair with rebuild=True."""
    # Test repair with rebuild
    response = await client.post(
        f"/system/indices/{index_manager.alias_name}/repair/",
        params={"rebuild": True},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_manager.alias_name in response_data["message"]

    await wait_for_all_tasks()

    # Verify index still exists after rebuild
    index_name = await index_manager.get_current_index_name()
    exists = await es_client.indices.exists(index=index_name)
    assert exists

    # Verify the robot automation was indexed in Elasticsearch
    await es_client.indices.refresh(index=index_name)
    es_response = await es_client.search(
        index=index_name, body={"query": {"term": {"_id": str(automation_id)}}}
    )

    assert es_response["hits"]["total"]["value"] == 1
    es_doc = es_response["hits"]["hits"][0]["_source"]
    assert es_doc["robot_id"] == str(robot_id)
    assert "query" in es_doc
    enhancement_type_field = "reference.enhancements.content.enhancement_type"
    assert (
        es_doc["query"]["bool"]["should"][0]["term"][enhancement_type_field]
        == "annotation"
    )


async def sub_test_robot_automation_update_without_rebuild(  # noqa: PLR0913
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
    index_manager: IndexManager,
    automation_id: uuid.UUID,
    robot_id: uuid.UUID,
    automation: SQLRobotAutomation,
) -> None:
    """Sub-test: Test robot automation repair with rebuild=False after SQL update."""
    # Update SQL data - modify the robot automation query
    index_name = index_manager.alias_name

    automation.query = {
        "bool": {
            "should": [
                {
                    "term": {
                        "reference.enhancements.content.enhancement_type": "abstract"
                    }
                },
                {"term": {"reference.visibility": "public"}},
            ],
            "minimum_should_match": 1,
        }
    }
    await session.commit()

    # Test repair without rebuild to update existing data
    response = await client.post(
        f"/system/indices/{index_name}/repair/",
        params={"rebuild": False},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    await wait_for_all_tasks()

    # Verify the updated robot automation is reflected in Elasticsearch
    await es_client.indices.refresh(index=index_name)
    es_response = await es_client.search(
        index=index_name, body={"query": {"term": {"_id": str(automation_id)}}}
    )

    assert es_response["hits"]["total"]["value"] == 1
    es_doc = es_response["hits"]["hits"][0]["_source"]
    assert es_doc["robot_id"] == str(robot_id)
    assert "query" in es_doc
    # Verify the updated query structure
    should_conditions = es_doc["query"]["bool"]["should"]
    assert len(should_conditions) == 2
    # Check for the updated conditions
    enhancement_field = "reference.enhancements.content.enhancement_type"
    enhancement_types = [
        condition["term"].get(enhancement_field)
        for condition in should_conditions
        if enhancement_field in condition.get("term", {})
    ]
    visibility_types = [
        condition["term"].get("reference.visibility")
        for condition in should_conditions
        if "reference.visibility" in condition.get("term", {})
    ]
    assert "abstract" in enhancement_types
    assert "public" in visibility_types


@pytest.fixture
def app() -> FastAPI:
    """Create a test FastAPI app with the utils router."""
    app = FastAPI(
        exception_handlers={
            NotFoundError: not_found_exception_handler,
        }
    )
    app.include_router(system_routes.router)
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_repair_reference_index_with_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
) -> None:
    """Test repairing the reference index with rebuild flag and distributed chunks."""
    # Ensure index exists first
    index_manager = system_routes.reference_index_manager(es_client)
    await index_manager.initialize_index()

    # Create 5 references with identifiers and enhancements
    references: list[SQLReference] = []
    for i in range(5):
        reference_id = uuid.uuid4()
        reference = SQLReference(id=reference_id, visibility=Visibility.PUBLIC)
        session.add(reference)
        references.append(reference)

        identifier = SQLExternalIdentifier.from_domain(
            LinkedExternalIdentifierFactory.build(
                reference_id=reference_id,
                identifier=DOIIdentifierFactory.build(
                    identifier=f"10.1234/test-ref-{i}"
                ),
            )
        )
        session.add(identifier)

        enhancement = SQLEnhancement.from_domain(
            EnhancementFactory.build(
                reference_id=reference_id,
                source="test_source",
                content=AnnotationEnhancementFactory.build(),
            )
        )
        session.add(enhancement)

    await session.commit()

    # Use small chunk_size to force multiple distributed tasks
    original_chunk_size = reference_tasks.settings.es_reference_repair_chunk_size
    reference_tasks.settings.es_reference_repair_chunk_size = 2

    try:
        # Test repair with rebuild - should create 3 chunks for 5 records
        index_name = index_manager.alias_name
        response = await client.post(
            f"/system/indices/{index_name}/repair/",
            params={"rebuild": True},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        await wait_for_all_tasks()

        # Verify all 5 references were indexed
        await es_client.indices.refresh(index=index_name)
        es_response = await es_client.search(
            index=index_name, body={"query": {"match_all": {}}}
        )

        assert es_response["hits"]["total"]["value"] == 5
        indexed_ids = {hit["_id"] for hit in es_response["hits"]["hits"]}
        expected_ids = {str(ref.id) for ref in references}
        assert indexed_ids == expected_ids
    finally:
        reference_tasks.settings.es_reference_repair_chunk_size = original_chunk_size

    # Run sub-test for update without rebuild using first reference
    await sub_test_reference_index_update_without_rebuild(
        client, es_client, session, index_manager, references[0].id, references[0]
    )


async def test_rebuild_index_maintains_shard_number(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
) -> None:
    """Test that repairing an index maintains the number of shards."""
    # Ensure index exists first with specific shard count
    index_manager = system_routes.reference_index_manager(es_client)

    assert index_manager.number_of_shards is None

    # Update the number of shards to 3
    index_manager.number_of_shards = 3
    await index_manager.migrate()

    # Shard count is never actually set on the system router
    # so set back to None
    index_manager.number_of_shards = None

    # Repair the index
    response = await client.post(
        f"/system/indices/{index_manager.alias_name}/repair/",
        params={"rebuild": True},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED

    await wait_for_all_tasks()

    # Verify the number of shards remains the same
    index_name = await index_manager.get_current_index_name()
    index_settings = await es_client.indices.get_settings(index=index_name)
    actual_shard_count = int(
        index_settings[index_name]["settings"]["index"]["number_of_shards"]
    )
    assert actual_shard_count == 3


async def test_repair_robot_automation_percolation_index_with_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
) -> None:
    """Test repairing the robot automation percolation index with rebuild flag."""
    # Ensure index exists first
    index_manager = system_routes.robot_automation_percolation_index_manager(es_client)
    await index_manager.initialize_index()

    # Add sample robot and robot automation to SQL
    robot_id = uuid.uuid4()
    robot = SQLRobot(
        id=robot_id,
        client_secret="test-secret",
        description="Test robot for automation",
        name="Test Robot",
        owner="test_owner",
    )
    session.add(robot)
    await session.commit()

    # Add robot automation
    automation_id = uuid.uuid4()
    automation = SQLRobotAutomation(
        id=automation_id,
        robot_id=robot_id,
        query={
            "bool": {
                "should": [
                    {
                        "term": {
                            "reference.enhancements.content.enhancement_type": (
                                "annotation"
                            )
                        }
                    }
                ],
                "minimum_should_match": 1,
            }
        },
    )
    session.add(automation)
    await session.commit()

    # Run sub-tests
    await sub_test_robot_automation_initial_rebuild(
        client, es_client, index_manager, automation_id, robot_id
    )
    await sub_test_robot_automation_update_without_rebuild(
        client, es_client, session, index_manager, automation_id, robot_id, automation
    )


async def test_repair_nonexistent_index(
    client: AsyncClient,
    # Required to allow successful obtainig of es_client as a system router dependency
    es_manager_for_tests: AsyncESClientManager,  # noqa: ARG001
) -> None:
    """Test attempting to repair a non-existent index returns appropriate error."""
    nonexistent_index_name = "non-existent-index"

    response = await client.post(
        f"/system/indices/{nonexistent_index_name}/repair/",
        params={"rebuild": False},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    response_data = response.json()
    assert (
        response_data["detail"]
        == "meta:index with alias non-existent-index does not exist."
    )


@pytest.mark.usefixtures("stubbed_jwks_response")
async def test_repair_auth_failure(
    client: AsyncClient,
    fake_application_id: str,
) -> None:
    """Test attempting to repair an index with missing and incorrect auth fails."""
    from app.core.config import Environment

    # Set up production environment and auth settings
    system_routes.settings.env = Environment.PRODUCTION
    system_routes.settings.azure_application_id = fake_application_id
    system_routes.system_utility_auth.reset()

    test_index_name = "test-index"

    # Test with invalid token
    response = await client.post(
        f"/system/indices/{test_index_name}/repair/",
        params={"rebuild": False},
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Test with missing auth header
    response = await client.post(
        f"/system/indices/{test_index_name}/repair/",
        params={"rebuild": False},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == '{"detail":"Authorization HTTPBearer header missing."}'

    # Clean up
    system_routes.system_utility_auth.reset()
    system_routes.settings.__init__()  # type: ignore[call-args, misc]
