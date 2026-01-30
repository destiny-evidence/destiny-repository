"""Generic repositories define expected functionality."""

import math
from abc import ABC
from collections.abc import Collection
from typing import Generic
from uuid import UUID

from opentelemetry import trace
from pydantic import UUID4
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    InstrumentedAttribute,
    RelationshipProperty,
    joinedload,
    selectinload,
)
from sqlalchemy.orm.strategy_options import _AbstractLoad

from app.core.config import get_settings
from app.core.exceptions import (
    SQLIntegrityError,
    SQLNotFoundError,
    SQLValueError,
)
from app.core.telemetry.attributes import (
    Attributes,
    trace_attribute,
)
from app.core.telemetry.repository import trace_repository_method
from app.persistence.generics import GenericDomainModelType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.generics import (
    GenericSQLPersistenceType,
    GenericSQLPreloadableType,
)
from app.persistence.sql.persistence import RelationshipLoadType

tracer = trace.get_tracer(__name__)
settings = get_settings()


class GenericAsyncSqlRepository(
    Generic[
        GenericDomainModelType, GenericSQLPersistenceType, GenericSQLPreloadableType
    ],
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

    def _get_relationship_loads(
        self,
        preload: list[GenericSQLPreloadableType] | None = None,
        depth: int = 1,
    ) -> list[_AbstractLoad]:
        """
        Get a list of relationship loading strategies with support for nesting.

        Args:
            preload: List of relationships to preload
            depth: Internal tracker for max relationship depth

        Returns:
            A list of ORM loading options configured for the relationships

        """
        if not preload:
            return []

        loaders: list[_AbstractLoad] = []

        for attribute_name in preload:
            attribute: InstrumentedAttribute | None = getattr(
                self._persistence_cls, attribute_name, None
            )
            if not attribute or not isinstance(
                attribute.property, RelationshipProperty
            ):
                # Not a relationship, perhaps a calculated attribute, skip
                continue

            relationship = attribute
            load_type = relationship.info.get("load_type", RelationshipLoadType.JOINED)
            max_recursion_depth = relationship.info.get("max_recursion_depth")

            # Determine the base loading strategy
            if load_type == RelationshipLoadType.SELECTIN:
                # Recurse once, we add more loads dynamically below
                loader = selectinload(relationship, recursion_depth=1)
            else:
                loader = joinedload(relationship)

            # This magic ensures we both:
            # - propagate preloads to self-referential relationships
            # - recursively join self-referential relationships a set number of times
            # Use-case for initial implementation is propagating enhancements etc to
            # duplicates when preloaded.
            avoid_propagate: set[str] = set()
            if back_populates := relationship.info.get("back_populates"):
                # Don't "bounce back" and form a joining cycle
                avoid_propagate.add(back_populates)
            if depth == (max_recursion_depth or 1):
                # Recursion exit case, maximum length of this relationship's
                # self-referential chain
                avoid_propagate.add(relationship.key)

            is_self_referential = (
                relationship.prop.mapper.class_ == self._persistence_cls
            )
            if preload and is_self_referential:
                loader = loader.options(
                    *self._get_relationship_loads(
                        [p for p in preload if p not in avoid_propagate], depth + 1
                    )
                )

            loaders.append(loader)

        return loaders

    def _validate_fields_exist(self, field_names: list[str]) -> None:
        """
        Validate provided field names exist on the persistence model.

        Raises SQLValueError if any are invalid.
        """
        mapper = inspect(self._persistence_cls)
        valid_columns = {c.key for c in mapper.column_attrs}
        invalid_fields = [key for key in field_names if key not in valid_columns]
        if invalid_fields:
            msg = (
                f"Invalid field(s) for {self._persistence_cls.__name__}: "
                f"{invalid_fields}"
            )
            raise SQLValueError(msg)

    @trace_repository_method(tracer)
    async def get_by_pk(
        self, pk: UUID, preload: list[GenericSQLPreloadableType] | None = None
    ) -> GenericDomainModelType:
        """
        Get a record using its primary key.

        Args:
        - pk (UUID): The primary key to use to look up the record.
        - preload (list[str]): A list of attributes to preload using a join.

        Raises:
        - NotFoundError: If the record is not found.

        """
        trace_attribute(Attributes.DB_PK, str(pk))
        options = self._get_relationship_loads(preload)
        query = (
            select(self._persistence_cls)
            .where(self._persistence_cls.id == pk)
            .options(*options)
        )
        try:
            result = (await self._session.execute(query)).unique().scalar_one()
        except NoResultFound as exc:
            detail = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            ) from exc
        return result.to_domain(preload=preload)

    @trace_repository_method(tracer)
    async def get_by_pks(
        self,
        pks: Collection[UUID],
        preload: list[GenericSQLPreloadableType] | None = None,
        *,
        fail_on_missing: bool = True,
    ) -> list[GenericDomainModelType]:
        """
        Get records using their primary keys.

        Args:
        - pks (list[UUID]): The primary keys to use to look up the records.
        - preload (list[str]): A list of attributes to preload using a join.
        - fail_on_missing (bool): Whether to raise an error if any records are
          missing. Defaults to True.

        Returns:
        - list[GenericDomainModelType]: A list of domain models.

        Raises:
        - SQLNotFoundError: If any of the records do not exist.

        """
        options = self._get_relationship_loads(preload)
        query = (
            select(self._persistence_cls)
            .where(self._persistence_cls.id.in_(pks))
            .options(*options)
        )
        result = await self._session.execute(query)
        db_references = result.unique().scalars().all()

        if len(db_references) != len(pks) and fail_on_missing:
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
        self, preload: list[GenericSQLPreloadableType] | None = None
    ) -> list[GenericDomainModelType]:
        """
        Get all records in the repository.

        This method should be used sparingly!

        Args:
        - preload (list[str]): A list of attributes to preload using a join.

        Returns:
        - list[GenericDomainModelType]: A list of domain models.

        """
        options = self._get_relationship_loads(preload)
        query = select(self._persistence_cls).options(*options)
        result = await self._session.execute(query)
        return [ref.to_domain(preload=preload) for ref in result.scalars().all()]

    @trace_repository_method(tracer)
    async def verify_pk_existence(self, pks: list[UUID]) -> None:
        """
        Check if every pk exists in the database.

        Args:
            pks (list[UUID]): List of primary keys to check.

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
    async def update_by_pk(self, pk: UUID, **kwargs: object) -> GenericDomainModelType:
        """
        Update a record using its primary key.

        Args:
        - pk (UUID): The primary key to use to look up the record.
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
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()

    @trace_repository_method(tracer)
    async def delete_by_pk(self, pk: UUID) -> None:
        """
        Delete a record using its primary key.

        Args:
        - pk (UUID): The primary key to use to look up the record.

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
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()

    @trace_repository_method(tracer)
    async def add_bulk(
        self, records: Collection[GenericDomainModelType]
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
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
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
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()

    @trace_repository_method(tracer)
    async def get_all_pks(
        self,
        min_id: UUID | None = None,
        max_id: UUID | None = None,
    ) -> list[UUID]:
        """
        Get all primary keys in the repository.

        Generally used as a convenience method before calling another bulk
        method that requires primary keys.

        :min_id: Inclusive lower bound for primary keys to return.
        :type min_id: UUID | None
        :max_id: Inclusive upper bound for primary keys to return.
        :type max_id: UUID | None

        :rtype: list[UUID]

        """
        query = select(self._persistence_cls.id)
        if min_id:
            query = query.where(self._persistence_cls.id >= min_id)
        if max_id:
            query = query.where(self._persistence_cls.id <= max_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    @trace_repository_method(tracer)
    async def get_partition_boundaries(
        self, partition_size: int
    ) -> list[tuple[UUID, UUID]]:
        """
        Get partition boundaries for the records in the repository.

        Samples boundary IDs at regular intervals based on partition_size,
        returning [start_id, end_id] tuples suitable for parallel processing.

        :param partition_size: Approximate number of records per partition.
        :type partition_size: int
        :return: List of inclusive [start_id, end_id] tuples.
        :rtype: list[tuple[UUID, UUID]]

        """
        total = await self.count()

        if total == 0:
            return []

        partitions = select(
            self._persistence_cls.id.label("id"),
            func.ntile(math.ceil(total / partition_size))
            .over(order_by=self._persistence_cls.id)
            .label("tile"),
        ).subquery()

        query = (
            select(func.min(partitions.c.id), func.max(partitions.c.id))
            .group_by(partitions.c.tile)
            .order_by(partitions.c.tile)
        )

        result = await self._session.execute(query)
        return [(row[0], row[1]) for row in result.fetchall()]

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
        - SQLValueError: If field names in kwargs do not exist on the persistence model.

        """
        trace_attribute(Attributes.DB_RECORD_COUNT, len(pks))
        trace_attribute(Attributes.DB_PARAMS, list(kwargs.keys()))

        if not pks:
            return 0

        # Validate all field names exist on the persistence model
        self._validate_fields_exist(list(kwargs.keys()))

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
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
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
        - SQLValueError: If field names do not exist on the persistence model.

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
        all_field_names = list({**filter_conditions, **kwargs}.keys())
        self._validate_fields_exist(all_field_names)

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
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e
        else:
            return result.rowcount or 0

    @trace_repository_method(tracer)
    async def find(
        self,
        order_by: str | None = None,
        limit: int | None = None,
        preload: list[GenericSQLPreloadableType] | None = None,
        **filters: object,
    ) -> list[GenericDomainModelType]:
        """
        Find records based on provided field filters.

        Args:
        - limit (int | None): Maximum number of records to return.
        - order_by (str | None): Field name to order the results by.
        - preload (list[str]): A list of attributes to preload using a join.
        - **filters**: Field filters (name -> value).
          Only fields on the model are applied. None values match using SQL IS NULL.

        Returns:
        - list[GenericDomainModelType]: A list of domain models matching the filters.

        """
        options = self._get_relationship_loads(preload)

        # Validate filter and order_by field names
        fields_to_validate = list(filters.keys())
        if order_by:
            fields_to_validate.append(order_by)
        self._validate_fields_exist(fields_to_validate)

        query = select(self._persistence_cls).options(*options)

        for field_name, value in filters.items():
            field = getattr(self._persistence_cls, field_name)
            if value is None:
                query = query.where(field.is_(None))
            else:
                query = query.where(field == value)

        if order_by:
            query = query.order_by(getattr(self._persistence_cls, order_by))

        if limit is not None:
            query = query.limit(limit)

        result = await self._session.execute(query)
        return [record.to_domain(preload=preload) for record in result.scalars().all()]

    @trace_repository_method(tracer)
    async def count(self) -> int:
        """
        Count the number of records in the repository.

        Returns:
        - int: The number of records.

        """
        query = select(func.count(self._persistence_cls.id))
        result = await self._session.execute(query)
        return result.scalar_one()
