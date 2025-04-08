from uuid import UUID

import pytest

from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.domain.imports.models.models import ImportRecord


class DummyDomainSQLModel(DomainBaseModel, SQLAttributeMixin): ...


class FakeRepository:
    def __init__(self, init_entries: list[DummyDomainSQLModel] | None = None):
        self.repository: dict[UUID, DummyDomainSQLModel] = {
            e.id: e for e in init_entries or []
        }

    async def add(self, record: DummyDomainSQLModel) -> DummyDomainSQLModel:
        self.repository[record.id] = record
        return record

    async def get_by_pk(
        self, pk: UUID, preload: list[str] | None = None
    ) -> DummyDomainSQLModel | None:
        return self.repository.get(pk)

    async def update_by_pk(self, pk: UUID, **kwargs: object) -> DummyDomainSQLModel:
        if pk not in self.repository:
            raise RuntimeError
        for key, value in kwargs.items():
            setattr(self.repository[pk], key, value)
        return self.repository[pk]

    async def delete_by_pk(self, pk) -> None:
        if pk not in self.repository:
            raise RuntimeError
        del self.repository[pk]


class FakeUnitOfWork:
    def __init__(
        self,
        batches=None,
        imports=None,
        results=None,
        references=None,
        external_identifiers=None,
        enhancements=None,
    ):
        self.batches = batches
        self.imports = imports
        self.results = results
        self.references = references
        self.external_identifiers = external_identifiers
        self.enhancements = enhancements
        self.committed = False

    async def __aenter__(self):
        self._is_active = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self._is_active = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


@pytest.fixture
def fake_import_record():
    """Function to construct a fake ImportRecord with a given record_id"""

    def _fake_import_record(record_id: UUID) -> ImportRecord:
        return ImportRecord(
            id=record_id,
            search_string="search string",
            searched_at="2025-02-02T13:29:30Z",
            processor_name="Test Importer",
            processor_version="0.0.1",
            notes="test import",
            expected_reference_count=100,
            source_name="OpenAlex",
        )

    return _fake_import_record


@pytest.fixture
def fake_repository():
    return FakeRepository


@pytest.fixture
def fake_uow():
    return FakeUnitOfWork
