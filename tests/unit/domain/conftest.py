from uuid import UUID, uuid4

import pytest

from app.core.exceptions import SQLNotFoundError
from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportRecord,
    ImportResult,
)


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
    ) -> DummyDomainSQLModel:
        # Currently just ignoring preloading in favour of creating
        # models with the data needed.
        if pk not in self.repository:
            raise SQLNotFoundError(
                detail=f"{pk} not in repository",
                lookup_value=pk,
                lookup_type="id",
                lookup_model="dummy-sql-model",
            )
        return self.repository[pk]

    async def update_by_pk(self, pk: UUID, **kwargs: object) -> DummyDomainSQLModel:
        if pk not in self.repository:
            raise SQLNotFoundError(
                detail=f"{pk} not in repository",
                lookup_value=pk,
                lookup_type="id",
                lookup_model="dummy-sql-model",
            )
        for key, value in kwargs.items():
            setattr(self.repository[pk], key, value)
        return self.repository[pk]

    async def delete_by_pk(self, pk) -> None:
        if pk not in self.repository:
            raise SQLNotFoundError(
                detail=f"{pk} not in repository",
                lookup_value=pk,
                lookup_type="id",
                lookup_model="dummy-sql-model",
            )
        del self.repository[pk]

    async def merge(self, record: DummyDomainSQLModel) -> DummyDomainSQLModel:
        """Merge a record into the repository, adding it if it doesn't exist."""
        if record.id not in self.repository:
            self.repository[record.id] = record
        else:
            existing_record = self.repository[record.id]
            for key, value in record.model_dump().items():
                setattr(existing_record, key, value)
        return self.repository[record.id]

    async def verify_pk_existence(self, pks: list[UUID]) -> None:
        """Verify that the given primary keys exist in the repository.

        Args:
            pks (list[UUID]): The primary keys to verify.

        Raises:
            SQLNotFoundError: If any of the primary keys do not exist in the repository.
        """
        missing_pks = {str(pk) for pk in pks if pk not in self.repository}
        if missing_pks:
            detail = f"{missing_pks} not in repository"
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self.__class__.__name__,
                lookup_type="id",
                lookup_value=missing_pks,
            )

    def iter_records(self):
        """Create an iterator over the records in the repository
        Returns:
            iterator[DummyDomainSQLModel]: iterator over the records in the repository
        """
        return iter(self.repository.values())

    def get_first_record(self) -> DummyDomainSQLModel:
        """Get the first record from the repository

        Returns:
            DummyDomainSQLModel: The first record in the FakeRepository

        Raises:
            RuntimeError: if the repository contains no records
        """
        record = next(self.iter_records(), None)
        if not record:
            error = "No record found in FakeRepository"
            raise RuntimeError(error)
        return record


class FakeUnitOfWork:
    def __init__(
        self,
        batches=None,
        imports=None,
        results=None,
        references=None,
        external_identifiers=None,
        enhancements=None,
        enhancement_requests=None,
        batch_enhancement_requests=None,
        robots=None,
    ):
        self.batches = batches
        self.imports = imports
        self.results = results
        self.references = references
        self.external_identifiers = external_identifiers
        self.enhancements = enhancements
        self.enhancement_requests = enhancement_requests
        self.batch_enhancement_requests = batch_enhancement_requests
        self.robots = robots
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


def __fake_import_record(id: UUID) -> ImportRecord:
    return ImportRecord(
        id=id,
        search_string="search string",
        searched_at="2025-02-02T13:29:30Z",
        processor_name="Test Importer",
        processor_version="0.0.1",
        notes="test import",
        expected_reference_count=100,
        source_name="OpenAlex",
    )


@pytest.fixture
def fake_import_record():
    """Fixture to construct a fake ImportRecord with a given record_id"""
    return __fake_import_record


@pytest.fixture
def fake_import_batch():
    """Fixture to construct a fake BatchRecord with a given record_id"""

    def _fake_import_batch(
        id: UUID, status: ImportBatchStatus, import_results: list[ImportResult]
    ) -> ImportBatch:
        import_record_id = uuid4()

        return ImportBatch(
            id=id,
            storage_url="https://www.totallyrealstorage.com",
            status=status,
            import_record_id=import_record_id,
            import_record=__fake_import_record(import_record_id),
            import_results=import_results,
        )

    return _fake_import_batch


@pytest.fixture
def fake_repository():
    return FakeRepository


@pytest.fixture
def fake_uow():
    return FakeUnitOfWork
