"""Unit tests for the ReferenceService class."""

import uuid

import pytest

from app.domain.references.models.models import (
    AnnotationEnhancement,
    EnhancementCreate,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifierCreate,
    Reference,
)
from app.domain.references.service import ReferenceService


@pytest.mark.asyncio
async def test_get_reference_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo)
    service = ReferenceService(uow)
    result = await service.get_reference(dummy_id)
    assert result.id == dummy_reference.id


@pytest.mark.asyncio
async def test_get_reference_not_found(fake_repository, fake_uow):
    repo = fake_repository()
    uow = fake_uow(references=repo)
    service = ReferenceService(uow)
    dummy_id = uuid.uuid4()
    result = await service.get_reference(dummy_id)
    assert result is None


@pytest.mark.asyncio
async def test_register_reference_happy_path(fake_repository, fake_uow):
    repo = fake_repository()
    uow = fake_uow(references=repo)
    service = ReferenceService(uow)
    created = await service.register_reference()
    # Verify that an id was assigned during registration.
    assert hasattr(created, "id")
    assert isinstance(created.id, uuid.UUID)


@pytest.mark.asyncio
async def test_register_enhancement_request_happy_path(fake_repository, fake_uow):
    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = ReferenceService(uow)

    enhancement_request = await service.trigger_enhancement_request(
        reference_id=uuid.uuid4(), enhancement_type=EnhancementType.BIBLIOGRAPHIC
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request


@pytest.mark.asyncio
async def test_update_enhancement_request_completed(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()
    enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        enhancement_type=EnhancementType.ANNOTATION,
        request_status=EnhancementRequestStatus.CREATED,
    )

    fake_enhancement_requests = fake_repository([enhancement_request])
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = ReferenceService(uow)

    updated_enhancement_request = await service.update_enhancement_request(
        request_id=enhancement_request_id,
        request_status=EnhancementRequestStatus.COMPLETED,
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert updated_enhancement_request == stored_request
    assert (
        updated_enhancement_request.request_status == EnhancementRequestStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_update_enhancement_request_failed_with_error(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        enhancement_type=EnhancementType.ANNOTATION,
        request_status=EnhancementRequestStatus.CREATED,
    )

    fake_enhancement_requests = fake_repository([enhancement_request])
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = ReferenceService(uow)

    updated_request = await service.update_enhancement_request(
        request_id=enhancement_request_id,
        request_status=EnhancementRequestStatus.FAILED,
        error="it bronked",
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert updated_request == stored_request
    assert updated_request.request_status == EnhancementRequestStatus.FAILED
    assert updated_request.error == "it bronked"


@pytest.mark.asyncio
async def test_add_identifier_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo_refs = fake_repository(init_entries=[dummy_reference])
    repo_ids = fake_repository()
    uow = fake_uow(references=repo_refs, external_identifiers=repo_ids)
    service = ReferenceService(uow)
    identifier_data = {"identifier": "W1234", "identifier_type": "open_alex"}
    fake_identifier_create = ExternalIdentifierCreate(**identifier_data)
    returned_identifier = await service.add_identifier(dummy_id, fake_identifier_create)
    assert getattr(returned_identifier, "reference_id", None) == dummy_id
    for k, v in identifier_data.items():
        assert getattr(returned_identifier, k, None) == v


@pytest.mark.asyncio
async def test_add_enhancement_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo_refs = fake_repository(init_entries=[dummy_reference])
    repo_enh = fake_repository()
    uow = fake_uow(references=repo_refs, enhancements=repo_enh)
    service = ReferenceService(uow)
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
async def test_add_identifier_reference_not_found(fake_repository, fake_uow):
    repo_refs = fake_repository()
    repo_ids = fake_repository()
    uow = fake_uow(references=repo_refs, external_identifiers=repo_ids)
    service = ReferenceService(uow)
    dummy_id = uuid.uuid4()
    fake_identifier_create = ExternalIdentifierCreate(
        identifier="W1234", identifier_type="open_alex"
    )
    with pytest.raises(RuntimeError):
        await service.add_identifier(dummy_id, fake_identifier_create)


@pytest.mark.asyncio
async def test_add_enhancement_reference_not_found(fake_repository, fake_uow):
    repo_refs = fake_repository()
    repo_enh = fake_repository()
    uow = fake_uow(references=repo_refs, enhancements=repo_enh)
    service = ReferenceService(uow)
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
    with pytest.raises(RuntimeError):
        await service.add_enhancement(dummy_id, fake_enhancement_create)
