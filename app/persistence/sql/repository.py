"""Generic repositories define expected functionality."""

import re
from abc import ABC
from typing import Generic

from pydantic import UUID4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import SQLDuplicateError, SQLNotFoundError
from app.persistence.generics import GenericDomainModelType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.generics import GenericSQLPersistenceType


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

        return await result.to_domain(preload=preload)

    async def update_by_pk(self, pk: UUID4, **kwargs: object) -> GenericDomainModelType:
        """
        Update a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.
        - kwargs (object): The attributes to update.

        Raises:
        - NotFoundError: If the record is not found.

        """
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

        await self._session.flush()
        await self._session.refresh(persistence)
        return await persistence.to_domain()

    async def delete_by_pk(self, pk: UUID4) -> None:
        """
        Delete a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.

        """
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
        persistence = await self._persistence_cls.from_domain(record)
        try:
            self._session.add(persistence)
            await self._session.flush()
        except IntegrityError as e:
            detail = f"""
Unable to add {self._persistence_cls.__name__}: duplicate.
"""
            lookup_type = "id"
            lookup_value = str(persistence.id)

            # Try extract details from the exception message.
            # (There's no nice way to check for duplicate unique keys before handling
            # the exception.)

            try:
                err_str = str(e)

                # Extract constraint name using regex
                constraint_match = re.search(r'constraint\s+"([^"]+)"', err_str)
                if constraint_match:
                    lookup_type = constraint_match.group(1)

                # Extract detail information using regex
                detail_match = re.search(r"DETAIL:\s+(.+?)(?:\n|$)", err_str)
                if detail_match:
                    detail = f"Duplicate entry: {detail_match.group(1).strip()}"
                    lookup_value = detail_match.group(1).strip()

            except Exception:  # noqa: BLE001
                lookup_type, lookup_value = "unknown", "unknown"

            finally:
                raise SQLDuplicateError(
                    detail=detail,
                    lookup_model=self._persistence_cls.__name__,
                    lookup_type=lookup_type,
                    lookup_value=lookup_value,
                ) from e

        await self._session.refresh(persistence)
        return await persistence.to_domain()

    async def merge(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Merge a record into the repository.

        If the record already exists in the database based on the PK, it will be
        updated. If it does not exist, it will be added.
        See also: https://docs.sqlalchemy.org/en/20/orm/session_state_management.html#merge-tips

        Args:
        - record (T): The record to be persisted.

        """
        persistence = await self._persistence_cls.from_domain(record)
        persistence = await self._session.merge(persistence)
        await self._session.flush()
        await self._session.refresh(persistence)
        return await persistence.to_domain()
