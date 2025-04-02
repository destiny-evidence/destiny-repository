"""Unit tests for the ReferenceService class."""

import uuid

import pytest

from app.domain.references.models.models import (
    AnnotationEnhancement,
    Enhancement,
    EnhancementCreate,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    Reference,
)
from app.domain.references.service import ReferenceService


# Use fake repositories but with real model classes.
class FakeReferenceRepo:
    def __init__(self, reference):
        self.reference = reference

    async def get_by_pk(self, ref_id, preload=None):
        return self.reference

    async def add(self, ref: Reference):
        # Simulate creation by assigning a new id.
        ref.id = uuid.uuid4()
        return ref


class FakeIdentifierRepo:
    async def add(self, identifier: ExternalIdentifier):
        return identifier


class FakeEnhancementRepo:
    async def add(self, enhancement: Enhancement):
        return enhancement


class FakeAsyncSqlUnitOfWork:
    def __init__(self, reference):
        self.references = FakeReferenceRepo(reference)
        self.external_identifiers = FakeIdentifierRepo()
        self.enhancements = FakeEnhancementRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_get_reference_found():
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    fake_uow = FakeAsyncSqlUnitOfWork(dummy_reference)
    service = ReferenceService(fake_uow)
    result = await service.get_reference(dummy_id)
    assert result.id == dummy_reference.id


@pytest.mark.asyncio
async def test_get_reference_not_found():
    fake_uow = FakeAsyncSqlUnitOfWork(None)
    service = ReferenceService(fake_uow)
    dummy_id = uuid.uuid4()
    result = await service.get_reference(dummy_id)
    assert result is None


@pytest.mark.asyncio
async def test_register_reference():
    fake_uow = FakeAsyncSqlUnitOfWork(None)
    service = ReferenceService(fake_uow)
    created = await service.register_reference()
    # Verify that an id was assigned during registration.
    assert hasattr(created, "id")
    assert isinstance(created.id, uuid.UUID)


@pytest.mark.asyncio
async def test_add_identifier_success():
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    fake_uow = FakeAsyncSqlUnitOfWork(dummy_reference)
    service = ReferenceService(fake_uow)
    identifier_data = {"identifier": "W1234", "identifier_type": "open_alex"}
    fake_identifier_create = ExternalIdentifierCreate(**identifier_data)
    returned_identifier = await service.add_identifier(dummy_id, fake_identifier_create)
    # Verify that the returned identifier has the correct reference_id and data.
    assert getattr(returned_identifier, "reference_id", None) == dummy_id
    for k, v in identifier_data.items():
        assert getattr(returned_identifier, k, None) == v


@pytest.mark.asyncio
async def test_add_enhancement_success():
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    fake_uow = FakeAsyncSqlUnitOfWork(dummy_reference)
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
    assert getattr(returned_enhancement, "reference_id", None) == dummy_id
    for k, v in enhancement_data.items():
        if k == "content":
            assert returned_enhancement.content == AnnotationEnhancement(**v)
        else:
            assert getattr(returned_enhancement, k, None) == v


@pytest.mark.asyncio
async def test_add_identifier_reference_not_found():
    fake_uow = FakeAsyncSqlUnitOfWork(None)
    service = ReferenceService(fake_uow)
    dummy_id = uuid.uuid4()
    fake_identifier_create = ExternalIdentifierCreate(
        identifier="W1234", identifier_type="open_alex"
    )
    with pytest.raises(RuntimeError):
        await service.add_identifier(dummy_id, fake_identifier_create)


@pytest.mark.asyncio
async def test_add_enhancement_reference_not_found():
    fake_uow = FakeAsyncSqlUnitOfWork(None)
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
