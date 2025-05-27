import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Reference,
)
from app.domain.references.models.validators import BatchEnhancementResultValidator
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
    with (
        patch(
            "app.domain.references.services.batch_enhancement_service.upload_file_to_blob_storage",
            AsyncMock(
                return_value=BlobStorageFile(
                    location="minio",
                    container="cont",
                    path="p",
                    filename="f",
                )
            ),
        ),
        patch(
            "app.domain.references.services.batch_enhancement_service.get_signed_url",
            return_value="http://signed.url",
        ),
    ):
        result = await service.build_robot_request(references, batch_request)
        assert str(result.reference_storage_url) == "http://signed.url/"
        assert str(result.result_storage_url) == "http://signed.url/"


@pytest.mark.asyncio
async def test_validate_batch_enhancement_result_happy_path(fake_uow):
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=BlobStorageFile(
            location="minio",
            container="cont",
            path="p",
            filename="f",
        ),
    )
    service = BatchEnhancementService(fake_uow())
    ref_id = str(batch_request.reference_ids[0])
    mock_bytes = b'{"reference_id": "' + ref_id.encode() + b'"}\n'
    with (
        patch(
            "app.domain.references.services.batch_enhancement_service.get_file_from_blob_storage",
            AsyncMock(return_value=mock_bytes),
        ),
        patch(
            "app.domain.references.models.validators.BatchEnhancementResultValidator.from_raw",
            return_value=BatchEnhancementResultValidator(
                reference_ids=set(batch_request.reference_ids)
            ),
        ),
    ):
        result = await service.validate_batch_enhancement_result(batch_request)
        assert isinstance(result, BatchEnhancementResultValidator)
        assert result.reference_ids == set(batch_request.reference_ids)


@pytest.mark.asyncio
async def test_validate_batch_enhancement_result_missing_file(fake_uow):
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
        result_file=None,
    )
    service = BatchEnhancementService(fake_uow())
    with pytest.raises(RuntimeError):
        await service.validate_batch_enhancement_result(batch_request)


@pytest.mark.asyncio
async def test_finalise_and_store_batch_enhancement_result_statuses(fake_uow):
    batch_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4(), uuid.uuid4()],
        robot_id=uuid.uuid4(),
        request_status=BatchEnhancementRequestStatus.RECEIVED,
    )
    service = BatchEnhancementService(fake_uow())
    with patch(
        "app.domain.references.services.batch_enhancement_service.upload_file_to_blob_storage",
        AsyncMock(
            return_value=BlobStorageFile(
                location="minio",
                container="cont",
                path="p",
                filename="f",
            )
        ),
    ):
        validator = BatchEnhancementResultValidator(
            reference_ids=set(batch_request.reference_ids),
            parse_failures=[],
            robot_errors=[],
        )
        status, file = await service.finalise_and_store_batch_enhancement_result(
            batch_request,
            validator,
            ["ok1", "ok2"],
            [],
        )
        assert status == BatchEnhancementRequestStatus.COMPLETED
        status, file = await service.finalise_and_store_batch_enhancement_result(
            batch_request,
            validator,
            ["ok1"],
            ["fail1"],
        )
        assert status == BatchEnhancementRequestStatus.PARTIAL_FAILED
        status, file = await service.finalise_and_store_batch_enhancement_result(
            batch_request,
            validator,
            [],
            ["fail1", "fail2"],
        )
        assert status == BatchEnhancementRequestStatus.FAILED
        assert isinstance(file, BlobStorageFile)
