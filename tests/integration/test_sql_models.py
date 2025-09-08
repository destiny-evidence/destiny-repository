"""Integration tests for SQL interface."""

import datetime
import uuid

import pytest
from destiny_sdk.imports import ImportRecordStatus
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
from app.domain.references.models.models import Enhancement, Reference
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)


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
        ([ImportResultStatus.CREATED], ImportBatchStatus.STARTED),
        ([ImportResultStatus.STARTED], ImportBatchStatus.STARTED),
        ([ImportResultStatus.FAILED], ImportBatchStatus.FAILED),
        ([ImportResultStatus.COMPLETED], ImportBatchStatus.COMPLETED),
        (
            [ImportResultStatus.STARTED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.STARTED,
        ),
        (
            [ImportResultStatus.FAILED, ImportResultStatus.COMPLETED],
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
        callback_url=None,
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

    q = select(ImportBatch).where(ImportBatch.id == batch_id)
    res = (await session.execute(q)).unique().scalar_one_or_none()
    res = await session.get(
        ImportBatch, batch_id, options=[joinedload(ImportBatch.import_results)]
    )
    assert res
    assert res.to_domain().status == expected_status
