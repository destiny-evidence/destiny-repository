import uuid

import pytest

from app.domain.references.enhancement_service import EnhancementService
from app.domain.references.models.models import (
    AnnotationEnhancement,
    EnhancementCreate,
    EnhancementRequest,
    EnhancementRequestStatus,
    Reference,
)

ENHANCEMENT_DATA = {
    "source": "test_source",
    "visibility": "public",
    "content_version": uuid.uuid4(),
    "enhancement_type": "annotation",
    "content": {
        "enhancement_type": "annotation",
        "annotations": [
            {
                "annotation_type": "test_annotation",
                "label": "test_label",
                "data": {"foo": "bar"},
            }
        ],
    },
}


@pytest.mark.asyncio
async def test_add_enhancement_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo_refs = fake_repository(init_entries=[dummy_reference])
    repo_enh = fake_repository()
    uow = fake_uow(references=repo_refs, enhancements=repo_enh)
    service = EnhancementService(uow)
    enhancement_data = {
        "source": "test_source",
        "visibility": "public",
        "content_version": uuid.uuid4(),
        "enhancement_type": "annotation",
        "content": {
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "test_annotation",
                    "label": "test_label",
                    "data": {"foo": "bar"},
                }
            ],
        },
    }
    fake_enhancement_create = EnhancementCreate(**enhancement_data)
    returned_enhancement = await service.add_enhancement(
        dummy_id, fake_enhancement_create
    )
    assert returned_enhancement.reference_id == dummy_id
    for k, v in enhancement_data.items():
        if k == "content":
            assert returned_enhancement.content == AnnotationEnhancement(**v)
        else:
            assert getattr(returned_enhancement, k, None) == v


@pytest.mark.asyncio
async def test_add_enhancement_reference_not_found(fake_repository, fake_uow):
    repo_refs = fake_repository()
    repo_enh = fake_repository()
    uow = fake_uow(references=repo_refs, enhancements=repo_enh)
    service = EnhancementService(uow)
    dummy_id = uuid.uuid4()
    fake_enhancement_create = EnhancementCreate(
        source="test_source",
        visibility="public",
        content_version=uuid.uuid4(),
        enhancement_type="annotation",
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "test_annotation",
                    "label": "test_label",
                    "data": {"foo": "bar"},
                }
            ],
        },
    )
    with pytest.raises(RuntimeError, match=f"{dummy_id} does not exist"):
        await service.add_enhancement(dummy_id, fake_enhancement_create)

    assert True


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_happy_path(
    fake_repository, fake_uow
):
    reference_id = uuid.uuid4()
    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = EnhancementService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id,
        robot_id=uuid.uuid4(),
    )

    enhancement_request = await service.request_reference_enhancement(
        enhancement_request=received_enhancement_request
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request
    assert enhancement_request.request_status == EnhancementRequestStatus.ACCEPTED


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_rejected():
    """
    TODO(Jack): Add in a test for when a robot rejects a request to create
    an enhancement against areference.
    """


@pytest.mark.asyncio
async def test_get_enhancement_request_happy_path(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()
    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={"some": "parameters"},
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = EnhancementService(uow)

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert returned_enhancement_request == existing_enhancement_request


@pytest.mark.asyncio
async def test_get_enhancement_request_doesnt_exist(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = EnhancementService(uow)

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert not returned_enhancement_request


@pytest.mark.asyncio
async def test_create_reference_enhancement_happy_path(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()
    reference_id = uuid.uuid4()
    fake_enhancement_repo = fake_repository()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=reference_id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_repository([Reference(id=reference_id)]),
        enhancements=fake_enhancement_repo,
    )

    service = EnhancementService(uow)

    enhancement = await service.create_reference_enhancement(
        enhancement_request_id=enhancement_request_id,
        enhancement=EnhancementCreate(**ENHANCEMENT_DATA),
    )

    enhancement_request = await service.get_enhancement_request(enhancement_request_id)

    assert enhancement_request.request_status == EnhancementRequestStatus.COMPLETED
    assert enhancement == fake_enhancement_repo.get_first_record()


@pytest.mark.asyncio
async def test_mark_enhancement_request_as_failed(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
    )
    service = EnhancementService(uow)

    returned_enhancement_request = await service.mark_enhancement_request_failed(
        enhancement_request_id=enhancement_request_id, error="it broke"
    )

    assert (
        returned_enhancement_request.request_status == EnhancementRequestStatus.FAILED
    )
    assert returned_enhancement_request.error == "it broke"


@pytest.mark.asyncio
async def test_mark_enhancement_request_as_failed_request_non_existent(
    fake_repository, fake_uow
):
    missing_enhancement_request_id = uuid.uuid4()

    uow = fake_uow(
        enhancement_requests=fake_repository(),
    )
    service = EnhancementService(uow)

    with pytest.raises(RuntimeError):
        await service.mark_enhancement_request_failed(
            enhancement_request_id=missing_enhancement_request_id, error="it broke"
        )
