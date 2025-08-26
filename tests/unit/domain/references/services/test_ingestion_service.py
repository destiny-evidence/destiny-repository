"""Test the ingestion service."""

import uuid
from unittest.mock import AsyncMock, patch

import destiny_sdk
import pytest
from destiny_sdk.identifiers import DOIIdentifier

from app.domain.imports.models.models import CollisionStrategy
from app.domain.references.models.models import Reference
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.ingestion_service import IngestionService


@pytest.fixture
def reference_file_input():
    """Create a valid ReferenceFileInput object."""
    return destiny_sdk.references.ReferenceFileInput(
        identifiers=[DOIIdentifier(identifier="10.1234/5678", identifier_type="doi")]
    )


@pytest.fixture
def reference_input_json(reference_file_input):
    """Reference JSON string with valid identifiers."""
    return reference_file_input.model_dump_json()


@pytest.mark.asyncio
async def test_ingest_reference_discard_case(
    fake_uow, fake_repository, reference_file_input, reference_input_json
):
    """Test ingest_reference when detect_and_handle_collision returns None (discard)."""
    reference = Reference(id=uuid.uuid4())
    uow = fake_uow(references=fake_repository([reference]))
    mock_blob_repo = AsyncMock()
    service = IngestionService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    service.detect_and_handle_collision = AsyncMock(return_value=None)

    mock_create_result = ReferenceCreateResult(reference=reference_file_input)
    with patch(
        "app.domain.references.models.validators.ReferenceCreateResult.from_raw",
        AsyncMock(return_value=mock_create_result),
    ):
        result = await service.ingest_reference(
            record_str=reference_input_json,
            entry_ref=1,
            collision_strategy=CollisionStrategy.DISCARD,
        )

        assert result is None
        service.detect_and_handle_collision.assert_called_once_with(
            reference_file_input, CollisionStrategy.DISCARD
        )


@pytest.mark.asyncio
async def test_ingest_reference_error_case(
    fake_uow, fake_repository, reference_file_input, reference_input_json
):
    """Test ingest_reference when detect_and_handle_collision returns an error string.
    This tests the collision strategy FAIL case."""
    reference = Reference(id=uuid.uuid4())
    uow = fake_uow(references=fake_repository([reference]))
    mock_blob_repo = AsyncMock()
    service = IngestionService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    error_message = "Identifier(s) are already mapped on an existing reference"
    service.detect_and_handle_collision = AsyncMock(return_value=error_message)

    mock_create_result = ReferenceCreateResult(reference=reference_file_input)
    with patch(
        "app.domain.references.models.validators.ReferenceCreateResult.from_raw",
        AsyncMock(return_value=mock_create_result),
    ):
        result = await service.ingest_reference(
            record_str=reference_input_json,
            entry_ref=1,
            collision_strategy=CollisionStrategy.FAIL,
        )

        assert isinstance(result, ReferenceCreateResult)
        assert len(result.errors) == 2
        assert result.errors[0] == "Entry 1:"
        assert result.errors[1] == error_message
        service.detect_and_handle_collision.assert_called_once_with(
            reference_file_input, CollisionStrategy.FAIL
        )


@pytest.mark.asyncio
async def test_ingest_reference_new_reference_case(
    fake_uow, fake_repository, reference_file_input, reference_input_json
):
    """Test ingest_reference with a new reference (no collision)."""
    reference_id = uuid.uuid4()
    reference = Reference(id=reference_id)
    uow = fake_uow(references=fake_repository([reference]))
    mock_blob_repo = AsyncMock()
    service = IngestionService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    new_reference = Reference(id=uuid.uuid4())
    service.detect_and_handle_collision = AsyncMock(return_value=new_reference)

    uow.references.merge = AsyncMock(return_value=new_reference)

    mock_create_result = ReferenceCreateResult(reference=reference_file_input)
    with patch(
        "app.domain.references.models.validators.ReferenceCreateResult.from_raw",
        AsyncMock(return_value=mock_create_result),
    ):
        result = await service.ingest_reference(
            record_str=reference_input_json,
            entry_ref=1,
            collision_strategy=CollisionStrategy.APPEND,
        )

        assert isinstance(result, ReferenceCreateResult)
        assert result.reference_id == new_reference.id
        service.detect_and_handle_collision.assert_called_once_with(
            reference_file_input, CollisionStrategy.APPEND
        )
        uow.references.merge.assert_called_once_with(new_reference)


@pytest.mark.asyncio
async def test_ingest_reference_merge_with_errors(
    fake_uow, fake_repository, reference_file_input, reference_input_json
):
    """Test reference ingestion with validation errors but successful merge.
    This tests the partial success case."""
    reference_id = uuid.uuid4()
    reference = Reference(id=reference_id)
    uow = fake_uow(references=fake_repository([reference]))
    mock_blob_repo = AsyncMock()
    service = IngestionService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    merged_reference = Reference(id=uuid.uuid4())
    service.detect_and_handle_collision = AsyncMock(return_value=merged_reference)

    uow.references.merge = AsyncMock(return_value=merged_reference)

    mock_create_result = ReferenceCreateResult(
        reference=reference_file_input, errors=["Warning: missing title"]
    )
    with patch(
        "app.domain.references.models.validators.ReferenceCreateResult.from_raw",
        AsyncMock(return_value=mock_create_result),
    ):
        result = await service.ingest_reference(
            record_str=reference_input_json,
            entry_ref=2,
            collision_strategy=CollisionStrategy.APPEND,
        )

        assert isinstance(result, ReferenceCreateResult)
        assert result.reference_id == merged_reference.id
        assert len(result.errors) == 2
        assert result.errors[0] == "Entry 2:"
        assert result.errors[1] == "Warning: missing title"
        service.detect_and_handle_collision.assert_called_once_with(
            reference_file_input, CollisionStrategy.APPEND
        )
        uow.references.merge.assert_called_once_with(merged_reference)


@pytest.mark.asyncio
async def test_ingest_reference_parsing_failed(fake_uow, fake_repository):
    """Test ingest_reference when parsing fails."""
    reference = Reference(id=uuid.uuid4())
    uow = fake_uow(references=fake_repository([reference]))
    mock_blob_repo = AsyncMock()
    service = IngestionService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    mock_create_result = ReferenceCreateResult(
        reference=None, errors=["Invalid JSON format"]
    )
    with patch(
        "app.domain.references.models.validators.ReferenceCreateResult.from_raw",
        AsyncMock(return_value=mock_create_result),
    ):
        result = await service.ingest_reference(
            record_str='{"invalid json',
            entry_ref=3,
            collision_strategy=CollisionStrategy.APPEND,
        )

        assert isinstance(result, ReferenceCreateResult)
        assert result.reference is None
        assert len(result.errors) == 1
        assert result.errors[0] == "Invalid JSON format"
