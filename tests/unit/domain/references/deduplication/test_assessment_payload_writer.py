import json
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest

from app.domain.references.models.models import (
    DeduplicationFieldComparison,
    DeduplicationFieldStatus,
)
from app.domain.references.services.deduplication_assessment_recorder import (
    BlobAssessmentPayloadWriter,
)
from app.persistence.blob.models import BlobContainer, BlobStorageFile
from app.persistence.blob.repository import BlobRepository
from tests.unit.domain.references.deduplication.test_assessment_record import (
    build_assessment,
    scored_candidate,
)


@pytest.fixture
def blob_repository() -> AsyncMock:
    repository = AsyncMock(spec=BlobRepository)
    repository.upload_file_to_blob_storage.side_effect = (
        lambda content, path, filename, container, **_: BlobStorageFile(  # noqa: ARG005
            location="minio", container="operations", path=path, filename=filename
        )
    )
    return repository


@pytest.fixture
def writer(blob_repository: AsyncMock) -> BlobAssessmentPayloadWriter:
    return BlobAssessmentPayloadWriter(blob_repository=blob_repository)


async def test_payload_is_written_to_the_operations_container_under_the_record_id(
    writer: BlobAssessmentPayloadWriter,
    blob_repository: AsyncMock,
) -> None:
    record_id = uuid7()

    stored = await writer.write(
        payload_id=record_id, assessment=build_assessment([scored_candidate(0.95)])
    )

    call = blob_repository.upload_file_to_blob_storage.call_args.kwargs
    assert call["container"] == BlobContainer.OPERATIONS
    assert call["path"] == "deduplication-assessments"
    assert call["filename"] == f"{record_id}.json"
    assert (
        stored.location
        == f"minio://operations/deduplication-assessments/{record_id}.json"
    )


async def test_written_payload_reports_the_bytes_it_stored(
    writer: BlobAssessmentPayloadWriter,
    blob_repository: AsyncMock,
) -> None:
    stored = await writer.write(
        payload_id=uuid7(), assessment=build_assessment([scored_candidate(0.95)])
    )

    uploaded = blob_repository.upload_file_to_blob_storage.call_args.kwargs["content"]
    assert stored.size_bytes == len(uploaded.getvalue())


async def test_payload_carries_the_values_the_scorer_actually_compared(
    writer: BlobAssessmentPayloadWriter,
    blob_repository: AsyncMock,
) -> None:
    # The raw values can differ while the compared forms match, so only the
    # normalised pair explains why a field scored the way it did.
    assessment = build_assessment(
        [
            scored_candidate(
                0.95,
                field_comparisons={
                    "title": DeduplicationFieldComparison(
                        incoming_value="The Title: A Study.",
                        candidate_value="the title a study",
                        normalised_incoming_value="the title a study",
                        normalised_candidate_value="the title a study",
                        status=DeduplicationFieldStatus.COMPARED,
                        score=1.0,
                    )
                },
            )
        ]
    )

    await writer.write(payload_id=uuid7(), assessment=assessment)

    content = blob_repository.upload_file_to_blob_storage.call_args.kwargs["content"]
    written = json.loads(content.getvalue())
    comparison = written["scored_candidates"][0]["pair_result"]["field_comparisons"][
        "title"
    ]
    assert comparison["incoming_value"] == "The Title: A Study."
    assert comparison["normalised_incoming_value"] == "the title a study"
    assert comparison["normalised_candidate_value"] == "the title a study"


async def test_written_payload_is_the_serialised_assessment(
    writer: BlobAssessmentPayloadWriter,
    blob_repository: AsyncMock,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.95), scored_candidate(0.2, rank=2)]
    )

    await writer.write(payload_id=uuid7(), assessment=assessment)

    content = blob_repository.upload_file_to_blob_storage.call_args.kwargs["content"]
    written = json.loads(content.getvalue())
    assert written["incoming_reference_id"] == str(assessment.incoming_reference_id)
    assert [
        candidate["candidate"]["reference_id"]
        for candidate in written["scored_candidates"]
    ] == [str(s.candidate.reference_id) for s in assessment.scored_candidates]
