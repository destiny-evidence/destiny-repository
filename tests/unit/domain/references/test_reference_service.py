"""Unit tests for the ReferenceService class."""

import uuid

import pytest

from app.domain.references.models.models import (
    ExternalIdentifierCreate,
    Reference,
)
from app.domain.references.reference_service import ReferenceService


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
