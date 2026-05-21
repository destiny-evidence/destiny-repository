"""Tests ES repair functionality (and inherently the link between SQL and ES)."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import UUID, uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.api.exception_handlers import (
    invalid_payload_exception_handler,
    not_found_exception_handler,
)
from app.core.config import Environment
from app.core.exceptions import InvalidPayloadError, NotFoundError
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
    reference_id: UUID,
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
    # Identifiers are stored in PostgreSQL only, not ES


async def sub_test_reference_index_update_without_rebuild(  # noqa: PLR0913
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
    index_manager: IndexManager,
    reference_id: UUID,
    reference: SQLReference,
) -> None:
    """Sub-test: Test reference index repair with repair_all after SQL update."""
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

    # Test in-place repair_all to update existing data
    response = await client.post(
        f"/system/indices/{index_name}/repair/",
        params={"repair_all": True},
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
    # Identifiers are stored in PostgreSQL only, not ES


async def sub_test_robot_automation_initial_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    index_manager: IndexManager,
    automation_id: UUID,
    robot_id: UUID,
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
    automation_id: UUID,
    robot_id: UUID,
    automation: SQLRobotAutomation,
) -> None:
    """Sub-test: Test robot automation repair with repair_all after SQL update."""
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

    # Test in-place repair_all to update existing data
    response = await client.post(
        f"/system/indices/{index_name}/repair/",
        params={"repair_all": True},
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
            InvalidPayloadError: invalid_payload_exception_handler,
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
        reference_id = uuid7()
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

    # Use small batch size to force multiple distributed tasks
    original_batch_size = reference_tasks.settings.es_reference_repair_max_batch_size
    reference_tasks.settings.es_reference_repair_max_batch_size = 2

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
        reference_tasks.settings.es_reference_repair_max_batch_size = (
            original_batch_size
        )

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
    await index_manager.migrate(settings_changeset={"number_of_shards": 3})

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
    robot_id = uuid7()
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
    automation_id = uuid7()
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
        params={"repair_all": True},
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
    # Set up production environment and auth settings
    system_routes.settings.env = Environment.PRODUCTION
    system_routes.settings.azure_application_id = fake_application_id
    system_routes.system_utility_auth.reset()

    test_index_name = "test-index"

    # Test with invalid token
    response = await client.post(
        f"/system/indices/{test_index_name}/repair/",
        params={"repair_all": True},
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Test with missing auth header
    response = await client.post(
        f"/system/indices/{test_index_name}/repair/",
        params={"repair_all": True},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == '{"detail":"Authorization HTTPBearer header missing."}'

    # Clean up
    system_routes.system_utility_auth.reset()
    system_routes.settings.__init__()  # type: ignore[call-args, misc]


async def test_repair_reference_index_subset_indexes_only_supplied_ids(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
) -> None:
    """Subset repair re-indexes only the supplied reference IDs."""
    index_manager = system_routes.reference_index_manager(es_client)
    await index_manager.initialize_index()
    index_name = index_manager.alias_name

    targeted_ids: list[UUID] = []
    untargeted_ids: list[UUID] = []
    for i in range(4):
        reference_id = uuid7()
        session.add(SQLReference(id=reference_id, visibility=Visibility.PUBLIC))
        session.add(
            SQLExternalIdentifier.from_domain(
                LinkedExternalIdentifierFactory.build(
                    reference_id=reference_id,
                    identifier=DOIIdentifierFactory.build(
                        identifier=f"10.1234/subset-ref-{i}"
                    ),
                )
            )
        )
        session.add(
            SQLEnhancement.from_domain(
                EnhancementFactory.build(
                    reference_id=reference_id,
                    source="test_source",
                    content=AnnotationEnhancementFactory.build(),
                )
            )
        )
        (targeted_ids if i < 2 else untargeted_ids).append(reference_id)
    await session.commit()

    response = await client.post(
        f"/system/indices/{index_name}/repair/",
        json={"document_ids": [str(rid) for rid in targeted_ids]},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Subset repair task for 2 document(s)" in response_data["message"]
    assert index_name in response_data["message"]

    await wait_for_all_tasks()
    await es_client.indices.refresh(index=index_name)

    es_response = await es_client.search(
        index=index_name, body={"query": {"match_all": {}}, "size": 100}
    )
    indexed_ids = {hit["_id"] for hit in es_response["hits"]["hits"]}
    assert indexed_ids == {str(rid) for rid in targeted_ids}
    for rid in untargeted_ids:
        assert str(rid) not in indexed_ids


async def test_repair_subset_rejects_unsupported_index(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
) -> None:
    """Subset repair against an index without a subset task returns 422."""
    index_manager = system_routes.robot_automation_percolation_index_manager(es_client)
    await index_manager.initialize_index()

    response = await client.post(
        f"/system/indices/{index_manager.alias_name}/repair/",
        json={"document_ids": [str(uuid7())]},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Subset repair is not supported" in response.json()["detail"]


async def test_repair_subset_rejects_rebuild_combo(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
) -> None:
    """Subset body + rebuild=true is incoherent and returns 422."""
    index_manager = system_routes.reference_index_manager(es_client)
    await index_manager.initialize_index()

    response = await client.post(
        f"/system/indices/{index_manager.alias_name}/repair/",
        params={"rebuild": True},
        json={"document_ids": [str(uuid7())]},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "rebuild=true" in response.json()["detail"]


async def test_repair_rejects_no_action(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
) -> None:
    """A request with no rebuild, repair_all, or document_ids returns 422."""
    index_manager = system_routes.reference_index_manager(es_client)
    await index_manager.initialize_index()

    response = await client.post(f"/system/indices/{index_manager.alias_name}/repair/")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Exactly one" in response.json()["detail"]


async def test_repair_subset_with_missing_id_is_rejected(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
) -> None:
    """A subset that includes any ID not present in SQL fails before queueing."""
    index_manager = system_routes.reference_index_manager(es_client)
    await index_manager.initialize_index()

    real_id = uuid7()
    session.add(SQLReference(id=real_id, visibility=Visibility.PUBLIC))
    await session.commit()

    missing_id = uuid7()
    response = await client.post(
        f"/system/indices/{index_manager.alias_name}/repair/",
        json={"document_ids": [str(real_id), str(missing_id)]},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert str(missing_id) in response.json()["detail"]
    assert str(real_id) not in response.json()["detail"]
