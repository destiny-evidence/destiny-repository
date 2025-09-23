"""Integration tests for SQL interface."""

import datetime
import uuid

import pytest
from destiny_sdk.imports import ImportRecordStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports.models.models import (
    CollisionStrategy,
    ImportBatchStatus,
    ImportResultStatus,
)
from app.domain.imports.models.sql import (
    ImportBatch,
    ImportRecord,
    ImportResult,
)
from app.domain.imports.repository import (
    ImportBatchSQLRepository,
    ImportResultSQLRepository,
)
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    PendingEnhancement,
    PendingEnhancementStatus,
    Reference,
)
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    EnhancementRequest as SQLEnhancementRequest,
)
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.repository import (
    EnhancementRequestSQLRepository,
)
from app.domain.robots.models.models import Robot
from app.domain.robots.models.sql import Robot as SQLRobot


async def test_enhancement_interface(
    session: AsyncSession,
):
    """Test that the enhancement content type is set correctly."""
    reference = SQLReference.from_domain(
        Reference(
            id=uuid.uuid4(),
        )
    )
    session.add(reference)
    enhancement_in = Enhancement(
        id=uuid.uuid4(),
        source="dummy",
        reference_id=reference.id,
        visibility="public",
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "openalex:topic",
                    "value": True,
                    "label": "test_label",
                    "data": {"foo": "bar"},
                }
            ],
        },
    )
    sql_enhancement = SQLEnhancement.from_domain(enhancement_in)
    session.add(sql_enhancement)
    await session.commit()

    # Check that we can query the JSONB content in psql
    result = await session.execute(
        text(
            """
            SELECT content->'enhancement_type' AS enhancement_type
            FROM enhancement
            WHERE id = :enhancement_id
            """
        ),
        {"enhancement_id": str(sql_enhancement.id)},
    )
    enhancement_type = result.scalar_one_or_none()
    assert enhancement_type == "annotation"

    # Check that the enhancement can be loaded from the database
    loaded_enhancement = await session.get(
        SQLEnhancement,
        sql_enhancement.id,
    )
    assert loaded_enhancement
    enhancement = loaded_enhancement.to_domain()
    assert enhancement == enhancement_in


@pytest.mark.parametrize(
    ("result_statuses", "expected_status"),
    [
        ([], ImportBatchStatus.CREATED),
        ([ImportResultStatus.CREATED], ImportBatchStatus.CREATED),
        ([ImportResultStatus.STARTED], ImportBatchStatus.STARTED),
        (
            [
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
            ],
            ImportBatchStatus.FAILED,
        ),
        ([ImportResultStatus.COMPLETED], ImportBatchStatus.COMPLETED),
        (
            [ImportResultStatus.STARTED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.STARTED,
        ),
        (
            [ImportResultStatus.FAILED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.PARTIALLY_FAILED,
        ),
        (
            [ImportResultStatus.PARTIALLY_FAILED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.PARTIALLY_FAILED,
        ),
    ],
)
async def test_import_batch_status_projection(
    session: AsyncSession,
    result_statuses: list[ImportResultStatus],
    expected_status: ImportBatchStatus,
):
    """Test ImportBatch status projection logic."""
    record_id = uuid.uuid4()
    record = ImportRecord(
        id=record_id,
        searched_at=datetime.datetime.now(tz=datetime.UTC),
        processor_name="test",
        processor_version="1.0",
        status=ImportRecordStatus.STARTED,
        expected_reference_count=-1,
        source_name="test",
    )
    session.add(record)
    batch_id = uuid.uuid4()
    batch = ImportBatch(
        id=batch_id,
        import_record_id=record_id,
        collision_strategy=CollisionStrategy.OVERWRITE,
        storage_url="https://example.com/bucket",
    )
    session.add(batch)
    for status in result_statuses:
        result = ImportResult(
            id=uuid.uuid4(),
            import_batch_id=batch_id,
            status=status,
            reference_id=None,
            failure_details=None,
        )
        session.add(result)
    await session.flush()
    await session.commit()

    repo = ImportBatchSQLRepository(session, ImportResultSQLRepository(session))
    assert (
        await repo.get_by_pk(batch_id, preload=["status"])
    ).status == expected_status


@pytest.mark.parametrize(
    ("pending_statuses", "expected_status"),
    [
        ([], None),  # No pending enhancements -> keep original status
        ([PendingEnhancementStatus.PENDING], EnhancementRequestStatus.RECEIVED),
        (
            [PendingEnhancementStatus.ACCEPTED],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [PendingEnhancementStatus.IMPORTING],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [PendingEnhancementStatus.INDEXING],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [PendingEnhancementStatus.COMPLETED],
            EnhancementRequestStatus.COMPLETED,
        ),
        (
            [PendingEnhancementStatus.FAILED],
            EnhancementRequestStatus.FAILED,
        ),
        (
            [
                PendingEnhancementStatus.COMPLETED,
                PendingEnhancementStatus.FAILED,
            ],
            EnhancementRequestStatus.PARTIAL_FAILED,
        ),
        (
            [
                PendingEnhancementStatus.COMPLETED,
                PendingEnhancementStatus.INDEXING_FAILED,
            ],
            EnhancementRequestStatus.PARTIAL_FAILED,
        ),
        (
            [
                PendingEnhancementStatus.FAILED,
                PendingEnhancementStatus.INDEXING_FAILED,
            ],
            EnhancementRequestStatus.PARTIAL_FAILED,
        ),
        (
            [
                PendingEnhancementStatus.PENDING,
                PendingEnhancementStatus.ACCEPTED,
            ],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [
                PendingEnhancementStatus.COMPLETED,
                PendingEnhancementStatus.IMPORTING,
            ],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [
                PendingEnhancementStatus.PENDING,
                PendingEnhancementStatus.INDEXING_FAILED,
            ],
            EnhancementRequestStatus.PROCESSING,
        ),
    ],
)
async def test_enhancement_request_status_projection(
    session: AsyncSession,
    pending_statuses: list[PendingEnhancementStatus],
    expected_status: EnhancementRequestStatus | None,
):
    """Test EnhancementRequest status projection logic."""
    # Create a reference first
    reference = SQLReference.from_domain(
        Reference(
            id=uuid.uuid4(),
        )
    )
    session.add(reference)

    # Create a robot first (required for foreign key constraint)
    robot_id = uuid.uuid4()
    robot = SQLRobot.from_domain(
        Robot(
            id=robot_id,
            name="Test Robot",
            description="A test robot",
            owner="test@example.com",
            base_url="https://example.com",
            client_secret="test-secret",
        )
    )
    session.add(robot)

    # Create an enhancement request
    request_id = uuid.uuid4()
    enhancement_request = SQLEnhancementRequest.from_domain(
        EnhancementRequest(
            id=request_id,
            reference_ids=[reference.id],
            robot_id=robot_id,
            request_status=EnhancementRequestStatus.RECEIVED,
        )
    )
    session.add(enhancement_request)

    # Create pending enhancements with different statuses
    for status in pending_statuses:
        pending_enhancement = SQLPendingEnhancement.from_domain(
            PendingEnhancement(
                id=uuid.uuid4(),
                reference_id=reference.id,
                robot_id=robot_id,
                enhancement_request_id=request_id,
                status=status,
            )
        )
        session.add(pending_enhancement)

    await session.flush()
    await session.commit()

    # Test the projection logic
    repo = EnhancementRequestSQLRepository(session)
    loaded_request = await repo.get_by_pk(request_id, preload=["status"])

    if expected_status is None:
        # Should keep original status when no pending enhancements
        assert loaded_request.request_status == EnhancementRequestStatus.RECEIVED
    else:
        assert loaded_request.request_status == expected_status
