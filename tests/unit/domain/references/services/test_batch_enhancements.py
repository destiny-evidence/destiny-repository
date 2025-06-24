import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import UUID4

from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Reference,
)
from app.domain.references.services.batch_enhancement_service import (
    BatchEnhancementService,
)
from app.persistence.blob.models import BlobStorageFile


@pytest.mark.asyncio
async def test_build_robot_request_happy_path(fake_uow, fake_repository):
    references = [Reference(id=uuid.uuid4()) for _ in range(2)]
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[r.id for r in references],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()
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
        mock_blob_repo, references, batch_request
    )
    assert str(result.reference_storage_url) == "http://signed.url/"
    assert str(result.result_storage_url) == "http://signed.url/"


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_happy_path(fake_uow, fake_repository):
    """
    Test that process_batch_enhancement_result yields expected messages and
    calls add_enhancement.
    """
    # Setup: create a BatchEnhancementRequest with a result_file
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(
                batch_request.reference_ids[0], as_error=False
            )

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    # Fake add_enhancement always returns success
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    # Collect all yielded messages
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == batch_request.reference_ids[0]
    assert not messages[0].error
    assert len(inserted_enhancement_ids) == 1
    updated = uow.batch_enhancement_requests.get_first_record()
    assert updated.request_status == BatchEnhancementRequestStatus.COMPLETED


def make_batch_enhancement_result_entry(reference_id: UUID4, *, as_error: bool) -> str:
    """
    Helper to create a BatchEnhancementResultEntry jsonl line (Enhancement or
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
async def test_process_batch_enhancement_result_handles_both_entry_types(
    fake_uow, fake_repository
):
    """
    Test process_batch_enhancement_result yields correct messages for both
    Enhancement and LinkedRobotError entries.
    """
    reference_id = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(reference_id, as_error=False)
            yield make_batch_enhancement_result_entry(reference_id, as_error=True)

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    # Fake add_enhancement returns success for enhancement
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert {m.error for m in messages} == {None, "robot error message"}
    assert len(inserted_enhancement_ids) == 1
    updated = uow.batch_enhancement_requests.get_first_record()
    # One success, one failure: should be PARTIAL_FAILED
    assert updated.request_status == BatchEnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_missing_reference_id(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result yields a message for missing
    reference ids in the result file.
    """
    reference_id_1 = uuid.uuid4()
    reference_id_2 = uuid.uuid4()  # This one will be missing from the result file
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id_1, reference_id_2],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(reference_id_1, as_error=False)

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert messages[1].reference_id == reference_id_2
    assert messages[1].error == "Requested reference not in batch enhancement result."
    assert len(inserted_enhancement_ids) == 1
    updated = uow.batch_enhancement_requests.get_first_record()
    # One success, one failure: should be PARTIAL_FAILED
    assert updated.request_status == BatchEnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_surplus_reference_id(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result ignores surplus reference ids in
    the result file.
    """
    reference_id_1 = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id_1],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    surplus_reference_id = uuid.uuid4()
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(reference_id_1, as_error=False)
            yield make_batch_enhancement_result_entry(
                surplus_reference_id, as_error=False
            )

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    # Fake add_enhancement returns success for enhancement
    async def fake_add_enhancement(enhancement):
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
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
    updated = uow.batch_enhancement_requests.get_first_record()
    # Only the expected reference succeeded, so should be completed
    assert updated.request_status == BatchEnhancementRequestStatus.PARTIAL_FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_parse_failure(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result yields a parse failure for
    malformed JSON.
    """
    reference_id = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield "not a json"

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    async def fake_add_enhancement(_):
        msg = "How did we get here?"
        raise AssertionError(msg)

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert messages[0].reference_id is None
    assert messages[0].error.startswith("Entry 1 could not be parsed:")
    assert len(inserted_enhancement_ids) == 0
    updated = uow.batch_enhancement_requests.get_first_record()
    assert updated.request_status == BatchEnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_add_enhancement_fails(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result yields error if add_enhancement
    returns False.
    """
    reference_id = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(reference_id, as_error=False)

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    async def fake_add_enhancement(_enhancement):
        return False, "Failed to add enhancement to reference."

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Failed to add enhancement to reference."
    assert len(inserted_enhancement_ids) == 0
    updated = uow.batch_enhancement_requests.get_first_record()
    assert updated.request_status == BatchEnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_all_enhancements_fail(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result yields errors and marks batch as
    failed if all enhancements fail.
    """
    reference_id = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(reference_id, as_error=False)

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    async def fake_add_enhancement(_enhancement):
        return False, "Failed to add enhancement to reference."

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]

    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Failed to add enhancement to reference."
    assert len(inserted_enhancement_ids) == 0
    updated = uow.batch_enhancement_requests.get_first_record()
    assert updated.request_status == BatchEnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_empty_result_file(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result yields missing reference messages
    if result file is empty.
    """
    reference_id = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            if False:
                yield  # never yields

    mock_blob_repo.stream_file_from_blob_storage = FakeStream

    async def fake_add_enhancement(_):
        return True, "Should not be called"

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 1
    assert messages[0].reference_id == reference_id
    assert messages[0].error == "Requested reference not in batch enhancement result."
    assert len(inserted_enhancement_ids) == 0
    updated = uow.batch_enhancement_requests.get_first_record()
    assert updated.request_status == BatchEnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_process_batch_enhancement_result_duplicate_reference_ids(
    fake_uow, fake_repository
):
    """
    Test that process_batch_enhancement_result processes duplicate reference ids
    in the result file.
    """
    reference_id = uuid.uuid4()
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[reference_id],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f.jsonl",
        ),
    )
    uow = fake_uow(batch_enhancement_requests=fake_repository([batch_request]))
    service = BatchEnhancementService(uow)
    mock_blob_repo = MagicMock()

    class FakeStream:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def __aiter__(self):
            yield make_batch_enhancement_result_entry(reference_id, as_error=False)
            yield make_batch_enhancement_result_entry(reference_id, as_error=False)

    mock_blob_repo.stream_file_from_blob_storage = FakeStream
    results = []

    async def fake_add_enhancement(enhancement):
        results.append(enhancement.reference_id)
        return True, f"Reference {enhancement.reference_id}: Enhancement added."

    inserted_enhancement_ids = set()
    messages = [
        msg
        async for msg in service.process_batch_enhancement_result(
            mock_blob_repo,
            batch_request,
            fake_add_enhancement,
            inserted_enhancement_ids,
        )
    ]
    assert len(messages) == 2
    assert messages[0].reference_id == reference_id
    assert messages[0].error is None
    assert messages[1].reference_id == reference_id
    assert messages[1].error is None
    assert len(inserted_enhancement_ids) == 2
    updated = uow.batch_enhancement_requests.get_first_record()
    # All succeeded, so should be completed
    assert updated.request_status == BatchEnhancementRequestStatus.COMPLETED
