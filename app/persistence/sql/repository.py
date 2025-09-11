"""Generic repositories define expected functionality."""

from abc import ABC
from typing import Generic

from opentelemetry import trace
from pydantic import UUID4
from sqlalchemy import select, update
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
        self.trace_domain_object_id(record)
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
    async def bulk_add(
        self, records: list[GenericDomainModelType]
    ) -> list[GenericDomainModelType]:
        """
        Add multiple records to the repository in bulk.

        Args:
        - records (list[T]): The records to be persisted.

        """
        trace_attribute(Attributes.DB_RECORD_COUNT, len(records))
        persistence_objects = [
            self._persistence_cls.from_domain(record) for record in records
        ]
        try:
            self._session.add_all(persistence_objects)
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        return [p.to_domain() for p in persistence_objects]

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
        trace_attribute(Attributes.DB_PK, str(record.id))
        self.trace_domain_object_id(record)
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

    @trace_repository_method(tracer)
    async def bulk_update(self, pks: list[UUID4], **kwargs: object) -> int:
        """
        Bulk update records by their primary keys.

        Args:
        - pks (list[UUID4]): The primary keys of records to update.
        - kwargs (object): The attributes to update.

        Returns:
        - int: The number of records updated.

        Raises:
        - SQLIntegrityError: If the update violates a constraint.
        - ValueError: If field names in kwargs do not exist on the persistence model.

        """
        trace_attribute(Attributes.DB_RECORD_COUNT, len(pks))
        trace_attribute(Attributes.DB_PARAMS, list(kwargs.keys()))

        if not pks:
            return 0

        # Validate all field names exist on the persistence model
        invalid_fields = [
            key for key in kwargs if not hasattr(self._persistence_cls, key)
        ]
        if invalid_fields:
            msg = (
                f"Invalid field(s) for {self._persistence_cls.__name__}: "
                f"{invalid_fields}"
            )
            raise ValueError(msg)

        if not kwargs:
            return 0

        try:
            stmt = (
                update(self._persistence_cls)
                .where(self._persistence_cls.id.in_(pks))
                .values(**kwargs)
            )
            result = await self._session.execute(stmt)
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e
        else:
            return result.rowcount or 0

    @trace_repository_method(tracer)
    async def bulk_update_by_filter(
        self, filter_conditions: dict[str, object], **kwargs: object
    ) -> int:
        """
        Bulk update records by filter conditions.

        Args:
        - filter_conditions (dict[str, object]): The conditions to filter records.
          None values will be matched using SQL IS NULL.
        - kwargs (object): The attributes to update. Can include None values.

        Returns:
        - int: The number of records updated.

        Raises:
        - SQLIntegrityError: If the update violates a constraint.
        - ValueError: If field names do not exist on the persistence model.

        Examples:
        - Update status to FAILED for all records with robot_enhancement_batch_id=123:
          bulk_update_by_filter({"robot_enhancement_batch_id": 123}, status="FAILED")

        - Update records where some_field is NULL:
          bulk_update_by_filter({"some_field": None}, new_value="updated")

        - Set a field to NULL:
          bulk_update_by_filter({"id": 123}, some_field=None)

        """
        # Trace filter conditions and update parameters
        all_field_keys = list({**filter_conditions, **kwargs}.keys())
        trace_attribute(Attributes.DB_PARAMS, all_field_keys)

        if not filter_conditions or not kwargs:
            return 0

        # Validate all field names exist on the persistence model
        all_fields = {**filter_conditions, **kwargs}
        invalid_fields = [
            key for key in all_fields if not hasattr(self._persistence_cls, key)
        ]
        if invalid_fields:
            msg = (
                f"Invalid field(s) for {self._persistence_cls.__name__}: "
                f"{invalid_fields}"
            )
            raise ValueError(msg)

        try:
            stmt = update(self._persistence_cls).values(**kwargs)

            for field_name, value in filter_conditions.items():
                field = getattr(self._persistence_cls, field_name)
                if value is None:
                    stmt = stmt.where(field.is_(None))
                else:
                    stmt = stmt.where(field == value)

            result = await self._session.execute(stmt)
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e
        else:
            return result.rowcount or 0

    @trace_repository_method(tracer)
    async def find(
        self,
        order_by: str | None = None,
        limit: int | None = None,
        preload: list[str] | None = None,
        **filters: object,
    ) -> list[GenericDomainModelType]:
        """
        Find records based on provided field filters.

        Args:
        - limit (int | None): Maximum number of records to return.
        - order_by (str | None): Field name to order the results by.
        - preload (list[str]): A list of attributes to preload using a join.
        - **filters: Field filters where key is field name and value is the
        filter value. Only fields that exist on the persistence model will be applied.
        None values are ignored.

        Returns:
        - list[GenericDomainModelType]: A list of domain models matching the filters.

        """
        options = []
        if preload:
            for p in preload:
                relationship = getattr(self._persistence_cls, p)
                options.append(joinedload(relationship))

        query = select(self._persistence_cls).options(*options)

        for field_name, value in filters.items():
            if value is not None and hasattr(self._persistence_cls, field_name):
                field = getattr(self._persistence_cls, field_name)
                query = query.where(field == value)

        if order_by and hasattr(self._persistence_cls, order_by):
            query = query.order_by(getattr(self._persistence_cls, order_by))

        if limit is not None:
            query = query.limit(limit)

        result = await self._session.execute(query)
        return [record.to_domain(preload=preload) for record in result.scalars().all()]
