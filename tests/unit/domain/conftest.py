from uuid import UUID, uuid7

import pytest

from app.core.exceptions import SQLNotFoundError
from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportRecord,
    ImportResult,
)
from app.domain.references.models.models import (
    PendingEnhancement,
    PendingEnhancementStatus,
)
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.robots.models.sql import Robot as SQLRobot
from tests.factories import PendingEnhancementFactory, ReferenceFactory, RobotFactory


class DummyDomainSQLModel(DomainBaseModel, SQLAttributeMixin): ...


class FakeRepository:
    def __init__(
        self,
        init_entries: list[DummyDomainSQLModel] | None = None,
        **child_repositories,
    ):
        self.repository: dict[UUID, DummyDomainSQLModel] = {
            e.id: e for e in init_entries or []
        }
        for key, value in child_repositories.items():
            self.__setattr__(key, value)

    async def add(self, record: DummyDomainSQLModel) -> DummyDomainSQLModel:
        self.repository[record.id] = record
        return record

    async def add_bulk(
        self, records: list[DummyDomainSQLModel]
    ) -> list[DummyDomainSQLModel]:
        """Add multiple records to the repository in bulk."""
        for record in records:
            self.repository[record.id] = record
        return records

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

    async def get_by_pks(
        self, pks: list[UUID], preload: list[str] | None = None
    ) -> list[DummyDomainSQLModel]:
        # Currently just ignoring preloading in favour of creating
        # models with the data needed.
        if not pks:
            return []
        records = [self.repository[pk] for pk in pks if pk in self.repository]
        if len(records) != len(pks):
            missing_pks = set(pks) - set(self.repository.keys())
            raise SQLNotFoundError(
                detail=f"{missing_pks} not in repository",
                lookup_value=missing_pks,
                lookup_type="id",
                lookup_model="dummy-sql-model",
            )
        return records

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
            for field in record.model_fields_set:
                setattr(existing_record, field, getattr(record, field))
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

    async def get_all(self) -> list[DummyDomainSQLModel]:
        """Get all records from the repository."""
        return list(self.repository.values())

    async def find(self, **kwargs) -> list[DummyDomainSQLModel]:
        """Find records matching the given criteria."""
        results = []
        if "order_by" in kwargs:
            del kwargs["order_by"]
        if "limit" in kwargs:
            del kwargs["limit"]
        for record in self.repository.values():
            match = True
            for key, value in kwargs.items():
                if not hasattr(record, key) or getattr(record, key) != value:
                    match = False
                    break
            if match:
                results.append(record)
        return results

    async def bulk_update(self, pks: list[UUID], **kwargs: object) -> int:
        """Update multiple records in the repository in bulk."""
        updated_count = 0
        for pk in pks:
            if pk in self.repository:
                for key, value in kwargs.items():
                    setattr(self.repository[pk], key, value)
                updated_count += 1
        return updated_count

    async def get_active_decision_determinations(
        self, reference_ids: set[UUID]
    ) -> dict[UUID, object]:
        """Return {reference_id: duplicate_determination} for active decisions."""
        if not reference_ids:
            return {}
        return {
            record.reference_id: record.duplicate_determination  # type: ignore[attr-defined]
            for record in self.repository.values()
            if getattr(record, "reference_id", None) in reference_ids
            and getattr(record, "active_decision", False) is True
        }

    async def bulk_update_by_filter(
        self, filter_conditions: dict, **kwargs: object
    ) -> int:
        """Update multiple records in the repository in bulk by filter."""
        updated_count = 0
        for record in self.repository.values():
            match = True
            for key, value in filter_conditions.items():
                if not hasattr(record, key) or getattr(record, key) != value:
                    match = False
                    break
            if match:
                for key, value in kwargs.items():
                    setattr(record, key, value)
                updated_count += 1
        return updated_count


def link_fake_repos(
    child_repo: "FakeRepository",
    parent_repo: "FakeRepository",
    *,
    fk: str,
    attr: str,
    filter_field: str | None = None,
    filter_value: object = None,
) -> None:
    """Simulate a SQLAlchemy viewonly relationship between FakeRepositories.

    After every ``merge`` on *child_repo*, the matching record in
    *parent_repo* (looked up via *fk* → parent PK) will have its
    *attr* set to the merged record — mirroring how SQLAlchemy syncs
    relationships within a session.

    An optional filter (e.g. ``filter_field="active_decision",
    filter_value=True``) restricts which merges trigger the sync.
    """
    _original = child_repo.merge

    async def _synced_merge(record):
        result = await _original(record)
        parent_id = getattr(result, fk, None)
        if (
            parent_id
            and parent_id in parent_repo.repository
            and (
                filter_field is None
                or getattr(result, filter_field, None) == filter_value
            )
        ):
            setattr(parent_repo.repository[parent_id], attr, result)
        return result

    child_repo.merge = _synced_merge  # type: ignore[method-assign]


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
        robots=None,
        robot_automations=None,
        reference_duplicate_decisions=None,
        pending_enhancements=None,
        robot_enhancement_batches=None,
    ):
        self.batches = batches
        self.imports = imports
        self.results = results
        self.references = references
        self.external_identifiers = external_identifiers
        self.enhancements = enhancements
        self.enhancement_requests = enhancement_requests
        self.robots = robots
        self.robot_automations = robot_automations
        self.reference_duplicate_decisions = reference_duplicate_decisions
        self.pending_enhancements = pending_enhancements
        self.robot_enhancement_batches = robot_enhancement_batches
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
        import_record_id = uuid7()

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
def fake_enhancement_data():
    return {
        "source": "test_source",
        "visibility": "public",
        "enhancement_type": "annotation",
        "content": {
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "openalex:topic",
                    "value": "true",
                    "label": "test_label",
                    "data": {"foo": "bar"},
                }
            ],
        },
    }


@pytest.fixture
def fake_repository():
    return FakeRepository


@pytest.fixture
def fake_uow():
    return FakeUnitOfWork


@pytest.fixture
async def created_reference(session):
    """Fixture to create and persist a test reference in the database."""
    reference = ReferenceFactory.build()
    sql_reference = SQLReference.from_domain(reference)
    session.add(sql_reference)
    await session.flush()
    return reference


@pytest.fixture
async def created_robot(session):
    """Fixture to create and persist a test robot in the database."""
    robot = RobotFactory.build(client_secret="test-secret")
    sql_robot = SQLRobot.from_domain(robot)
    session.add(sql_robot)
    await session.flush()
    return robot


@pytest.fixture
def pending_enhancement_factory(session, created_reference, created_robot):
    """Factory fixture to create pending enhancements with configurable parameters."""

    async def _create_pending_enhancement(
        status: PendingEnhancementStatus = PendingEnhancementStatus.PENDING,
        expires_at=None,
        source: str = "test",
        retry_of: UUID | None = None,
        **kwargs,
    ) -> PendingEnhancement:
        pending_enhancement = PendingEnhancementFactory.build(
            reference_id=created_reference.id,
            robot_id=created_robot.id,
            status=status,
            source=source,
            retry_of=retry_of,
            **kwargs,
        )
        if expires_at is not None:
            pending_enhancement.expires_at = expires_at

        sql_pending_enhancement = SQLPendingEnhancement.from_domain(pending_enhancement)
        session.add(sql_pending_enhancement)
        await session.flush()
        return pending_enhancement

    return _create_pending_enhancement


@pytest.fixture
async def created_pending_enhancement(pending_enhancement_factory):
    """Fixture to create and persist a test pending enhancement with default status."""
    return await pending_enhancement_factory()
