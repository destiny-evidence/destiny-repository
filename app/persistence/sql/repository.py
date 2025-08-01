"""Generic repositories define expected functionality."""

from abc import ABC
from typing import Generic

from opentelemetry import trace
from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import SQLIntegrityError, SQLNotFoundError
from app.core.telemetry.attributes import (
    Attributes,
    trace_attribute,
)
from app.core.telemetry.repository import trace_repository_method
from app.persistence.generics import GenericDomainModelType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.generics import GenericSQLPersistenceType

tracer = trace.get_tracer(__name__)


class GenericAsyncSqlRepository(
    Generic[GenericDomainModelType, GenericSQLPersistenceType],
    GenericAsyncRepository[GenericDomainModelType, GenericSQLPersistenceType],  # type:ignore[type-var]
    ABC,
):
    """A generic implementation of a repository backed by SQLAlchemy."""

    _session: AsyncSession

    def __init__(
        self,
        session: AsyncSession,
        domain_cls: type[GenericDomainModelType],
        persistence_cls: type[GenericSQLPersistenceType],
    ) -> None:
        """
        Initialize the repository.

        Args:
        - session (AsyncSession): The current active database session.
        - _persistence_cls (type[GenericSQLPersistenceType]):
            The SQL model which will be persisted.
        - _domain_cls (type[GenericDomainModelType]):
            The domain class of model which will be persisted.

        """
        self._session = session
        self._persistence_cls = persistence_cls
        self._domain_cls = domain_cls
        self.system = "SQL"

    @trace_repository_method(tracer)
    async def get_by_pk(
        self, pk: UUID4, preload: list[str] | None = None
    ) -> GenericDomainModelType:
        """
        Get a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.
        - preload (list[str]): A list of attributes to preload using a join.

        Raises:
        - NotFoundError: If the record is not found.

        """
        trace_attribute(Attributes.DB_PK, str(pk))
        options = []
        if preload:
            for p in preload:
                relationship = getattr(self._persistence_cls, p)
                options.append(joinedload(relationship))
        result = await self._session.get(self._persistence_cls, pk, options=options)
        if not result:
            detail = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            )
        return result.to_domain(preload=preload)

    @trace_repository_method(tracer)
    async def get_by_pks(
        self, pks: list[UUID4], preload: list[str] | None = None
    ) -> list[GenericDomainModelType]:
        """
        Get records using their primary keys.

        Args:
        - pks (list[UUID4]): The primary keys to use to look up the records.
        - preload (list[str]): A list of attributes to preload using a join.

        Returns:
        - list[GenericDomainModelType]: A list of domain models.

        Raises:
        - SQLNotFoundError: If any of the records do not exist.

        """
        options = []
        if preload:
            for p in preload:
                relationship = getattr(self._persistence_cls, p)
                options.append(joinedload(relationship))

        query = (
            select(self._persistence_cls)
            .where(self._persistence_cls.id.in_(pks))
            .options(*options)
        )
        result = await self._session.execute(query)
        db_references = result.unique().scalars().all()

        if len(db_references) != len(pks):
            missing_pks = set(pks) - {ref.id for ref in db_references}
            detail = (
                f"Unable to find {self._persistence_cls.__name__}"
                f" with pks {missing_pks}"
            )
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=missing_pks,
            )

        return [ref.to_domain(preload=preload) for ref in db_references]

    @trace_repository_method(tracer)
    async def get_all(
        self, preload: list[str] | None = None
    ) -> list[GenericDomainModelType]:
        """
        Get all records in the repository.

        This method should be used sparingly!

        Args:
        - preload (list[str]): A list of attributes to preload using a join.

        Returns:
        - list[GenericDomainModelType]: A list of domain models.

        """
        options = []
        if preload:
            for p in preload:
                relationship = getattr(self._persistence_cls, p)
                options.append(joinedload(relationship))

        query = select(self._persistence_cls).options(*options)
        result = await self._session.execute(query)
        return [ref.to_domain(preload=preload) for ref in result.scalars().all()]

    @trace_repository_method(tracer)
    async def verify_pk_existence(self, pks: list[UUID4]) -> None:
        """
        Check if every pk exists in the database.

        Args:
            pks (list[UUID4]): List of primary keys to check.

        Raises:
            SQLNotFoundError: If any of the records do not exist.

        """
        query = select(self._persistence_cls).where(self._persistence_cls.id.in_(pks))
        result = await self._session.execute(query)
        db_references = result.scalars().all()

        if len(db_references) != len(pks):
            missing_pks = set(pks) - {ref.id for ref in db_references}
            detail = (
                f"Unable to find {self._persistence_cls.__name__}"
                f" with pks {missing_pks}"
            )
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=missing_pks,
            )

    @trace_repository_method(tracer)
    async def update_by_pk(self, pk: UUID4, **kwargs: object) -> GenericDomainModelType:
        """
        Update a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.
        - kwargs (object): The attributes to update.

        Raises:
        - NotFoundError: If the record is not found.

        """
        trace_attribute(Attributes.DB_PK, str(pk))
        # Trace keys, not values
        trace_attribute(Attributes.DB_PARAMS, list(kwargs.keys()))
        persistence = await self._session.get(self._persistence_cls, pk)
        if not persistence:
            detail = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            )

        # Check if key is in the persistence model.
        for key, value in kwargs.items():
            setattr(persistence, key, value)

        try:
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()

    @trace_repository_method(tracer)
    async def delete_by_pk(self, pk: UUID4) -> None:
        """
        Delete a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.

        """
        trace_attribute(Attributes.DB_PK, str(pk))
        persistence = await self._session.get(self._persistence_cls, pk)
        if not persistence:
            detail = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            )

        await self._session.delete(persistence)
        await self._session.flush()

    @trace_repository_method(tracer)
    async def add(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Add a record to the repository.

        Args:
        - record (T): The record to be persisted.

        Note:
        This only adds a record to the session and flushes it. To persist the
        record after this transaction you will need to commit the session
        (generally through the unit of work).

        Note:
        If the record already exists in the database per its PK, it will be updated
        instead of added. Consider renaming to upsert().

        """
        trace_attribute(Attributes.DB_PK, str(record.id))
        persistence = self._persistence_cls.from_domain(record)
        try:
            self._session.add(persistence)
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()

    @trace_repository_method(tracer)
    async def merge(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Merge a record into the repository.

        If the record already exists in the database based on the PK, it will be
        updated. If it does not exist, it will be added.
        See also: https://docs.sqlalchemy.org/en/20/orm/session_state_management.html#merge-tips

        Args:
        - record (T): The record to be persisted.

        Raises:
        - SQLIntegrityError: If the record or any dependents already exists in the
        database and violate a unique constraint.

        """
        persistence = self._persistence_cls.from_domain(record)
        try:
            persistence = await self._session.merge(persistence)
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()

    @trace_repository_method(tracer)
    async def get_all_pks(self) -> list[UUID4]:
        """
        Get all primary keys in the repository.

        Generally used as a convenience method before calling another bulk
        method that requires primary keys.

        Returns:
        - list[UUID4]: A list of all primary keys in the repository.

        """
        query = select(self._persistence_cls.id)
        result = await self._session.execute(query)
        return [row[0] for row in result.fetchall()]
