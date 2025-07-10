"""Tests ES repair functionality (and inherently the link between SQL and ES)."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.core.exceptions import NotFoundError
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.domain.references.models.models import EnhancementType, Visibility
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
from app.main import not_found_exception_handler
from app.tasks import broker
from app.utils import routes as utils_routes


async def sub_test_reference_index_initial_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    index_name: str,
    reference_id: uuid.UUID,
) -> None:
    """Sub-test: Test reference index repair with rebuild=True."""
    # Test repair with rebuild
    response = await client.post(
        f"/system/elastic/indices/{index_name}/repair/", params={"rebuild": True}
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    # Wait for the task to complete
    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

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
    index_name: str,
    reference_id: uuid.UUID,
    reference: SQLReference,
) -> None:
    """Sub-test: Test reference index repair with rebuild=False after SQL update."""
    # Update SQL data - change visibility and add another identifier
    reference.visibility = Visibility.RESTRICTED
    new_identifier = SQLExternalIdentifier(
        id=uuid.uuid4(),
        reference_id=reference_id,
        identifier_type="pm_id",
        identifier="12345678",
    )
    session.add(new_identifier)
    await session.commit()

    # Test repair without rebuild to update existing data
    response = await client.post(
        f"/system/elastic/indices/{index_name}/repair/", params={"rebuild": False}
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    # Wait for the task to complete
    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

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
    index_name: str,
    automation_id: uuid.UUID,
    robot_id: uuid.UUID,
) -> None:
    """Sub-test: Test robot automation index repair with rebuild=True."""
    # Test repair with rebuild
    response = await client.post(
        f"/system/elastic/indices/{index_name}/repair/", params={"rebuild": True}
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    # Wait for the task to complete
    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

    # Verify index still exists after rebuild
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
    index_name: str,
    automation_id: uuid.UUID,
    robot_id: uuid.UUID,
    automation: SQLRobotAutomation,
) -> None:
    """Sub-test: Test robot automation repair with rebuild=False after SQL update."""
    # Update SQL data - modify the robot automation query
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
        f"/system/elastic/indices/{index_name}/repair/", params={"rebuild": False}
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "Repair task for index" in response_data["message"]
    assert index_name in response_data["message"]

    # Wait for the task to complete
    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

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
    app.include_router(utils_routes.router)
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
    """Test repairing the reference index with rebuild flag."""
    index_name = ReferenceDocument.Index.name

    # Ensure index exists first
    await ReferenceDocument.init(using=es_client)

    # Add sample data to SQL
    reference_id = uuid.uuid4()
    reference = SQLReference(
        id=reference_id,
        visibility=Visibility.PUBLIC,
    )
    session.add(reference)

    # Add identifier
    identifier = SQLExternalIdentifier(
        id=uuid.uuid4(),
        reference_id=reference_id,
        identifier_type="doi",
        identifier="10.1234/test-reference",
    )
    session.add(identifier)

    # Add enhancement
    enhancement = SQLEnhancement(
        id=uuid.uuid4(),
        reference_id=reference_id,
        visibility=Visibility.PUBLIC,
        source="test_source",
        enhancement_type=EnhancementType.ANNOTATION,
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "test:scheme",
                    "label": "test_label",
                    "value": True,
                }
            ],
        },
    )
    session.add(enhancement)
    await session.commit()

    # Run sub-tests
    await sub_test_reference_index_initial_rebuild(
        client, es_client, index_name, reference_id
    )
    await sub_test_reference_index_update_without_rebuild(
        client, es_client, session, index_name, reference_id, reference
    )


async def test_repair_robot_automation_percolation_index_with_rebuild(
    client: AsyncClient,
    es_client: AsyncElasticsearch,
    session: AsyncSession,
) -> None:
    """Test repairing the robot automation percolation index with rebuild flag."""
    index_name = RobotAutomationPercolationDocument.Index.name

    # Ensure index exists first
    await RobotAutomationPercolationDocument.init(using=es_client)

    # Add sample robot and robot automation to SQL
    robot_id = uuid.uuid4()
    robot = SQLRobot(
        id=robot_id,
        base_url="http://test-robot.com/",
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
        client, es_client, index_name, automation_id, robot_id
    )
    await sub_test_robot_automation_update_without_rebuild(
        client, es_client, session, index_name, automation_id, robot_id, automation
    )


async def test_repair_nonexistent_index(
    client: AsyncClient,
) -> None:
    """Test attempting to repair a non-existent index returns appropriate error."""
    nonexistent_index_name = "non-existent-index"

    response = await client.post(
        f"/system/elastic/indices/{nonexistent_index_name}/repair/",
        params={"rebuild": False},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    response_data = response.json()
    assert "Index non-existent-index not found" in response_data["detail"]
