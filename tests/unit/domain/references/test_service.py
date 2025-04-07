"""Unit tests for the ReferenceService class."""

import uuid

import pytest

from app.domain.references.models.models import (
    AnnotationEnhancement,
    EnhancementCreate,
    ExternalIdentifierCreate,
    Reference,
)
from app.domain.references.service import ReferenceService


class FakeUnitOfWork:
    def __init__(self, references=None, external_identifiers=None, enhancements=None):
        self.references = references
        self.external_identifiers = external_identifiers
        self.enhancements = enhancements
        self.committed = False
        super().__init__()

    async def __aenter__(self):
        self._is_active = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self._is_active = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


class FakeRepository:
    def __init__(self, init_entries: list | None = None):
        self.repository = {e.id: e for e in init_entries} if init_entries else {}

    async def add(self, record):
        self.repository[record.id] = record
        return record

    async def get_by_pk(self, pk, preload=None):
        return self.repository.get(pk)

    async def update_by_pk(self, pk, **kwargs: object):
        self.repository[pk] = kwargs.items()

    async def delete_by_pk(self, pk):
        self.repository.pop(pk)


@pytest.mark.asyncio
async def test_get_reference_happy_path():
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    fake_repo = FakeRepository(init_entries=[dummy_reference])
    fake_uow = FakeUnitOfWork(references=fake_repo)
    service = ReferenceService(fake_uow)
    result = await service.get_reference(dummy_id)
    assert result.id == dummy_reference.id


@pytest.mark.asyncio
async def test_get_reference_not_found():
    fake_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(references=fake_repo)
    service = ReferenceService(fake_uow)
    dummy_id = uuid.uuid4()
    result = await service.get_reference(dummy_id)
    assert result is None


@pytest.mark.asyncio
async def test_register_reference_happy_path():
    fake_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(references=fake_repo)
    service = ReferenceService(fake_uow)
    created = await service.register_reference()
    # Verify that an id was assigned during registration.
    assert hasattr(created, "id")
    assert isinstance(created.id, uuid.UUID)


@pytest.mark.asyncio
async def test_add_identifier_happy_path():
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    fake_references_repo = FakeRepository(init_entries=[dummy_reference])
    fake_identifiers_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(
        references=fake_references_repo, external_identifiers=fake_identifiers_repo
    )
    service = ReferenceService(fake_uow)
    identifier_data = {"identifier": "W1234", "identifier_type": "open_alex"}
    fake_identifier_create = ExternalIdentifierCreate(**identifier_data)
    returned_identifier = await service.add_identifier(dummy_id, fake_identifier_create)
    # Verify that the returned identifier has the correct reference_id and data.
    assert getattr(returned_identifier, "reference_id", None) == dummy_id
    for k, v in identifier_data.items():
        assert getattr(returned_identifier, k, None) == v


@pytest.mark.asyncio
async def test_add_enhancement_happy_path():
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    fake_references_repo = FakeRepository(init_entries=[dummy_reference])
    fake_enhancements_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(
        references=fake_references_repo, enhancements=fake_enhancements_repo
    )
    service = ReferenceService(fake_uow)
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
    # Verify that the returned enhancement has the correct reference_id and data.
    assert returned_enhancement.reference_id == dummy_id
    for k, v in enhancement_data.items():
        if k == "content":
            assert returned_enhancement.content == AnnotationEnhancement(**v)
        else:
            assert getattr(returned_enhancement, k, None) == v


@pytest.mark.asyncio
async def test_add_identifier_reference_not_found():
    fake_references_repo = FakeRepository()
    fake_identifiers_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(
        references=fake_references_repo, external_identifiers=fake_identifiers_repo
    )
    service = ReferenceService(fake_uow)
    dummy_id = uuid.uuid4()
    fake_identifier_create = ExternalIdentifierCreate(
        identifier="W1234", identifier_type="open_alex"
    )
    with pytest.raises(RuntimeError):
        await service.add_identifier(dummy_id, fake_identifier_create)


@pytest.mark.asyncio
async def test_add_enhancement_reference_not_found():
    fake_references_repo = FakeRepository()
    fake_enhancements_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(
        references=fake_references_repo, enhancements=fake_enhancements_repo
    )
    service = ReferenceService(fake_uow)
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
