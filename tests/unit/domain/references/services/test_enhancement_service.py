import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.references.models.models import (
    EnhancementRequest,
    EnhancementRequestStatus,
    PendingEnhancement,
    PendingEnhancementStatus,
    Reference,
    RobotResultValidationEntry,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.enhancement_service import (
    EnhancementService,
    ProcessedResults,
)
from app.persistence.blob.models import BlobStorageFile


def create_fake_stream(entries):
    """Helper to create a FakeStream that yields the given entries."""

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            for entry in entries:
                yield entry

    return FakeStream


def create_empty_stream():
    """Helper to create a FakeStream that yields nothing (empty file)."""

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            # Empty file - no lines yielded
            return
            yield  # Make it a generator

    return FakeStream


def create_enhancement_request(reference_ids, status=EnhancementRequestStatus.RECEIVED):
    """Helper to create an EnhancementRequest with result_file."""
    return EnhancementRequest(
        id=uuid.uuid7(),
        reference_ids=reference_ids,
        robot_id=uuid.uuid7(),
        request_status=status,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )


def create_pending_enhancement(reference_id, status=PendingEnhancementStatus.PENDING):
    """Helper to create a PendingEnhancement."""
    return PendingEnhancement(
        id=uuid.uuid7(),
        reference_id=reference_id,
        robot_id=uuid.uuid7(),
        enhancement_request_id=uuid.uuid7(),
        robot_enhancement_batch_id=uuid.uuid7(),
        status=status,
    )


def create_result_file():
    """Helper to create a BlobStorageFile for results."""
    return BlobStorageFile(
        location="minio",
        container="cont",
        path="p",
        filename="f.jsonl",
    )


def create_processed_results():
    """Helper to create a ProcessedResults instance."""
    return ProcessedResults(
        imported_enhancement_ids=set(),
        successful_pending_enhancement_ids=set(),
        failed_pending_enhancement_ids=set(),
    )


@pytest.mark.asyncio
async def test_build_robot_request_happy_path(fake_uow, fake_repository):
    references = [Reference(id=uuid.uuid7()) for _ in range(2)]
    enhancement_request = EnhancementRequest(
        id=uuid.uuid7(),
        reference_ids=[r.id for r in references],
        robot_id=uuid.uuid7(),
        request_status=EnhancementRequestStatus.RECEIVED,
    )
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))
    mock_blob_repo = MagicMock()
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)
    mock_blob_repo.upload_file_to_blob_storage = AsyncMock(
        return_value=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f",
        )
    )
    mock_blob_repo.get_signed_url = AsyncMock(return_value="http://signed.url/")
    result = await service.build_robot_request(
        mock_blob_repo, references, enhancement_request
    )
    assert str(result.reference_storage_url) == "http://signed.url/"
    assert str(result.result_storage_url) == "http://signed.url/"


@pytest.mark.asyncio
async def test_process_enhancement_result_happy_path(fake_uow, fake_repository):
    """
    Test that process_enhancement_result yields expected messages and
    calls add_enhancement.
    """
    reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    # Fake add_enhancement always returns success
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    # Collect all yielded messages
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert not messages[0].error
    assert len(inserted_enhancement_ids) == 1
    updated = uow.enhancement_requests.get_first_record()
    assert updated.request_status == EnhancementRequestStatus.COMPLETED


def make_enhancement_result_entry(reference_id: uuid.UUID, *, as_error: bool) -> str:
    """
    Helper to create a EnhancementResultEntry jsonl line (Enhancement or
    LinkedRobotError) with correct annotation structure.
    """
    if as_error:
        # LinkedRobotError
        return json.dumps(
            {"reference_id": str(reference_id), "message": "robot error message"}
        )
    # Enhancement with correct annotation structure
    return json.dumps(
        {
            "reference_id": str(reference_id),
            "enhancement_type": "annotation",
            "content": {
                "enhancement_type": "annotation",
                "annotations": [
                    {
                        "annotation_type": "boolean",
                        "scheme": "openalex:topic",
                        "label": "test_label",
                        "value": True,
                        "score": 0.95,
                        "data": {"foo": "bar"},
                    }
                ],
            },
            "source": "test_source",
            "visibility": "public",
        }
    )


@pytest.mark.asyncio
async def test_process_enhancement_result_handles_both_entry_types(
    fake_uow, fake_repository
):
    """
    Test process_enhancement_result yields correct messages for both
    Enhancement and LinkedRobotError entries.
    """
    reference_id_1 = uuid.uuid7()
    reference_id_2 = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id_1, reference_id_2])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id_1, as_error=False),
            make_enhancement_result_entry(reference_id_2, as_error=True),
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    # Fake add_enhancement returns success for enhancement
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert {m.error for m in messages} == {None, "robot error message"}
    assert len(inserted_enhancement_ids) == 1
    updated = uow.enhancement_requests.get_first_record()
    # One success, one failure: should be PARTIAL_FAILED
    assert updated.request_status == EnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_enhancement_result_missing_reference_id(
    fake_uow, fake_repository
):
    """
    Test that process_enhancement_result yields a message for missing
    reference ids in the result file.
    """
    reference_id_1 = uuid.uuid7()
    reference_id_2 = uuid.uuid7()  # This one will be missing from the result file
    enhancement_request = create_enhancement_request([reference_id_1, reference_id_2])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id_1, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    added_enhancements = []

    async def fake_add_enhancement(enhancement):
        added_enhancements.append(enhancement)
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert messages[1].reference_id == reference_id_2
    assert messages[1].error == "Requested reference not in enhancement result."
    assert len(inserted_enhancement_ids) == 1
    assert added_enhancements[0].id == inserted_enhancement_ids.pop()
    updated = uow.enhancement_requests.get_first_record()
    # One success, one failure: should be PARTIAL_FAILED
    assert updated.request_status == EnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_enhancement_result_surplus_reference_id(
    fake_uow, fake_repository
):
    """
    Test that process_enhancement_result ignores surplus reference ids in
    the result file.
    """
    reference_id_1 = uuid.uuid7()
    surplus_reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id_1])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id_1, as_error=False),
            make_enhancement_result_entry(surplus_reference_id, as_error=False),
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    # Fake add_enhancement returns success for enhancement
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert messages[0].reference_id == reference_id_1
    assert messages[0].error is None
    assert messages[1].reference_id == surplus_reference_id
    assert messages[1].error == "Reference not in batch enhancement request."
    assert len(inserted_enhancement_ids) == 1
    updated = uow.enhancement_requests.get_first_record()
    # Only the expected reference succeeded, so should be completed
    assert updated.request_status == EnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_enhancement_result_parse_failure(fake_uow, fake_repository):
    """
    Test that process_enhancement_result yields a parse failure for
    malformed JSON.
    """
    reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(["not a json"])
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(_):
        msg = "How did we get here?"
        raise AssertionError(msg)

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert messages[0].reference_id is None
    assert messages[0].error.startswith("Entry 1 could not be parsed:")
    assert len(inserted_enhancement_ids) == 0
    updated = uow.enhancement_requests.get_first_record()
    assert updated.request_status == EnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_enhancement_result_add_enhancement_fails(
    fake_uow, fake_repository
):
    """
    Test that process_enhancement_result yields error if add_enhancement
    returns False.
    """
    reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(_enhancement):
        return False, "Failed to add enhancement to reference."

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Failed to add enhancement to reference."
    assert len(inserted_enhancement_ids) == 0
    updated = uow.enhancement_requests.get_first_record()
    assert updated.request_status == EnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_enhancement_result_all_enhancements_fail(
    fake_uow, fake_repository
):
    """
    Test that process_enhancement_result yields errors and marks batch as
    failed if all enhancements fail.
    """
    reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(_enhancement):
        return False, "Failed to add enhancement to reference."

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]

    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Failed to add enhancement to reference."
    assert len(inserted_enhancement_ids) == 0
    updated = uow.enhancement_requests.get_first_record()
    assert updated.request_status == EnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_empty_result_file(
    fake_uow, fake_repository
):
    """
    Test that process_enhancement_result yields missing reference messages
    if result file is empty.
    """
    reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    mock_blob_repo.stream_file_from_blob_storage = create_empty_stream()
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(_):
        return True, "Should not be called"

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Requested reference not in enhancement result."
    assert len(inserted_enhancement_ids) == 0
    updated = uow.enhancement_requests.get_first_record()
    assert updated.request_status == EnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_enhancement_result_duplicate_reference_ids(
    fake_uow, fake_repository
):
    """
    Test that process_enhancement_result errors for duplicate reference ids
    in the result file.
    """
    reference_id = uuid.uuid7()
    enhancement_request = create_enhancement_request([reference_id])
    uow = fake_uow(enhancement_requests=fake_repository([enhancement_request]))

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id, as_error=False),
            make_enhancement_result_entry(reference_id, as_error=False),
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    results = []

    async def fake_add_enhancement(enhancement):
        results.append(enhancement.reference_id)
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_enhancement_result(
            mock_blob_repo,
            enhancement_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert messages[0].reference_id == reference_id
    assert messages[0].error is None
    assert messages[1].reference_id == reference_id
    assert messages[1].error == "Duplicate reference ID in enhancement result."
    assert len(inserted_enhancement_ids) == 1  # Only first enhancement processed
    assert len(results) == 1  # Only first enhancement processed
    updated = uow.enhancement_requests.get_first_record()
    # One succeeded, one failed: should be PARTIAL_FAILED
    assert updated.request_status == EnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_happy_path():
    """
    Test that process_robot_enhancement_batch_result yields expected messages and
    calls add_enhancement.
    """
    reference_id = uuid.uuid7()
    pending_enhancement = create_pending_enhancement(reference_id)
    result_file = create_result_file()

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), None)

    # Fake add_enhancement always returns success
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    results = create_processed_results()

    # Collect all yielded messages
    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert not messages[0].error
    assert len(results.imported_enhancement_ids) == 1
    assert {pending_enhancement.id} == results.successful_pending_enhancement_ids
    assert len(results.failed_pending_enhancement_ids) == 0


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_handles_both_entry_types():
    """
    Test process_robot_enhancement_batch_result yields correct messages for both
    Enhancement and LinkedRobotError entries.
    """
    reference_id_1 = uuid.uuid7()
    reference_id_2 = uuid.uuid7()

    pending_enhancement_1 = create_pending_enhancement(reference_id_1)
    pending_enhancement_2 = create_pending_enhancement(reference_id_2)
    result_file = create_result_file()

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id_1, as_error=False),
            make_enhancement_result_entry(reference_id_2, as_error=True),
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), None)

    # Fake add_enhancement returns success for enhancement
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement_1, pending_enhancement_2],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 2
    assert {m.error for m in messages} == {None, "robot error message"}
    assert len(results.imported_enhancement_ids) == 1
    # One succeeded, one failed
    assert {pending_enhancement_1.id} == results.successful_pending_enhancement_ids
    assert {pending_enhancement_2.id} == results.failed_pending_enhancement_ids


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_missing_reference_id():
    """
    Test that process_robot_enhancement_batch_result yields a message for missing
    reference ids in the result file.
    """
    reference_id_1 = uuid.uuid7()
    reference_id_2 = uuid.uuid7()  # This one will be missing from the result file

    pending_enhancement_1 = create_pending_enhancement(reference_id_1)
    pending_enhancement_2 = create_pending_enhancement(reference_id_2)
    result_file = create_result_file()

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id_1, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), None)

    added_enhancements = []

    async def fake_add_enhancement(enhancement):
        added_enhancements.append(enhancement)
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement_1, pending_enhancement_2],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 2
    assert messages[1].reference_id == reference_id_2
    assert messages[1].error == "Requested reference not in enhancement result."
    assert len(results.imported_enhancement_ids) == 1
    assert added_enhancements[0].id in results.imported_enhancement_ids
    # One succeeded, one failed
    assert {pending_enhancement_1.id} == results.successful_pending_enhancement_ids
    assert {pending_enhancement_2.id} == results.failed_pending_enhancement_ids


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_surplus_reference_id(fake_uow):
    """
    Test that process_robot_enhancement_batch_result handles surplus reference ids in
    the result file by ignoring them.
    """
    reference_id_1 = uuid.uuid7()
    surplus_reference_id = uuid.uuid7()

    pending_enhancement = create_pending_enhancement(reference_id_1)
    result_file = create_result_file()

    uow = fake_uow()
    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id_1, as_error=False),
            make_enhancement_result_entry(surplus_reference_id, as_error=False),
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    # Fake add_enhancement returns success for enhancement
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement],
            fake_add_enhancement,
            results,
        )
    ]
    # Should process both entries but only categorize the expected one
    assert len(messages) == 2
    assert messages[0].reference_id == reference_id_1
    assert messages[0].error is None
    assert messages[1].reference_id == surplus_reference_id
    # Surplus entries generate errors in batch processing
    assert messages[1].error == "Reference not in batch enhancement request."
    assert len(results.imported_enhancement_ids) == 1  # Only expected enhancement added
    assert {pending_enhancement.id} == results.successful_pending_enhancement_ids
    assert len(results.failed_pending_enhancement_ids) == 0


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_parse_failure(fake_uow):
    """
    Test that process_robot_enhancement_batch_result yields a parse failure for
    malformed JSON.
    """
    reference_id = uuid.uuid7()
    pending_enhancement = create_pending_enhancement(reference_id)
    result_file = create_result_file()

    uow = fake_uow()
    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(["not a json"])
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(_):
        msg = "How did we get here?"
        raise AssertionError(msg)

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement],
            fake_add_enhancement,
            results,
        )
    ]
    # Should have parse failure message + missing reference message
    assert len(messages) == 2
    assert messages[0].reference_id is None
    assert messages[0].error.startswith("Entry 1 could not be parsed:")
    assert messages[1].reference_id == reference_id
    assert messages[1].error == "Requested reference not in enhancement result."
    assert len(results.imported_enhancement_ids) == 0
    assert len(results.successful_pending_enhancement_ids) == 0
    assert {pending_enhancement.id} == results.failed_pending_enhancement_ids


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_add_enhancement_fails(fake_uow):
    """
    Test that process_robot_enhancement_batch_result yields error if add_enhancement
    returns False.
    """
    reference_id = uuid.uuid7()
    pending_enhancement = create_pending_enhancement(reference_id)
    result_file = create_result_file()

    uow = fake_uow()
    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [make_enhancement_result_entry(reference_id, as_error=False)]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(_enhancement):
        return False, "Failed to add enhancement to reference."

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Failed to add enhancement to reference."
    assert len(results.imported_enhancement_ids) == 0
    assert len(results.successful_pending_enhancement_ids) == 0
    assert {pending_enhancement.id} == results.failed_pending_enhancement_ids


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_empty_result_file():
    """
    Test that process_robot_enhancement_batch_result yields missing reference messages
    if result file is empty.
    """
    reference_id = uuid.uuid7()
    pending_enhancement = create_pending_enhancement(reference_id)
    result_file = create_result_file()

    mock_blob_repo = MagicMock()
    mock_blob_repo.stream_file_from_blob_storage = create_empty_stream()
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), None)

    async def fake_add_enhancement(_):
        msg = "How did we get here?"
        raise AssertionError(msg)

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Requested reference not in enhancement result."
    assert len(results.imported_enhancement_ids) == 0
    assert len(results.successful_pending_enhancement_ids) == 0
    assert {pending_enhancement.id} == results.failed_pending_enhancement_ids


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_duplicate_reference_ids():
    """
    Test that process_robot_enhancement_batch_result processes duplicate reference ids
    in the result file.
    """
    reference_id = uuid.uuid7()
    pending_enhancement = create_pending_enhancement(reference_id)
    result_file = create_result_file()

    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id, as_error=False),
            make_enhancement_result_entry(reference_id, as_error=False),
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), None)

    enhancement_results = []

    async def fake_add_enhancement(enhancement):
        enhancement_results.append(enhancement.reference_id)
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 2
    assert messages[0].reference_id == reference_id
    assert messages[0].error is None
    assert messages[1].reference_id == reference_id
    assert messages[1].error == "Duplicate reference ID in enhancement result."
    assert len(results.imported_enhancement_ids) == 1  # Only first enhancement added
    assert len(enhancement_results) == 1  # Only first enhancement processed
    # First entry succeeded, so pending enhancement is successful
    assert {pending_enhancement.id} == results.successful_pending_enhancement_ids
    assert len(results.failed_pending_enhancement_ids) == 0


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_result_multiple_pending_enhancements(
    fake_uow,
):
    """
    Test that process_robot_enhancement_batch_result correctly categorizes
    multiple pending enhancements with mixed success/failure.
    """
    reference_id_1 = uuid.uuid7()
    reference_id_2 = uuid.uuid7()
    reference_id_3 = uuid.uuid7()  # This one will fail

    pending_enhancement_1 = create_pending_enhancement(reference_id_1)
    pending_enhancement_2 = create_pending_enhancement(reference_id_2)
    pending_enhancement_3 = create_pending_enhancement(reference_id_3)
    result_file = create_result_file()

    uow = fake_uow()
    mock_blob_repo = MagicMock()
    fake_stream = create_fake_stream(
        [
            make_enhancement_result_entry(reference_id_1, as_error=False),
            make_enhancement_result_entry(reference_id_2, as_error=False),
            make_enhancement_result_entry(reference_id_3, as_error=True),  # Error
        ]
    )
    mock_blob_repo.stream_file_from_blob_storage = fake_stream
    service = EnhancementService(ReferenceAntiCorruptionService(mock_blob_repo), uow)

    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    results = create_processed_results()

    messages = [
        RobotResultValidationEntry.model_validate_json(msg)
        async for msg in service.process_robot_enhancement_batch_result(
            mock_blob_repo,
            result_file,
            [pending_enhancement_1, pending_enhancement_2, pending_enhancement_3],
            fake_add_enhancement,
            results,
        )
    ]
    assert len(messages) == 3
    assert messages[0].reference_id == reference_id_1
    assert messages[0].error is None
    assert messages[1].reference_id == reference_id_2
    assert messages[1].error is None
    assert messages[2].reference_id == reference_id_3
    assert messages[2].error == "robot error message"

    assert len(results.imported_enhancement_ids) == 2  # Only successful ones
    assert {
        pending_enhancement_1.id,
        pending_enhancement_2.id,
    } == results.successful_pending_enhancement_ids
    assert {pending_enhancement_3.id} == results.failed_pending_enhancement_ids
