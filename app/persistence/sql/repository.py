"""Generic repositories define expected functionality."""

from abc import ABC
from typing import Generic

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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

        :param session: The current active database session.
        :param domain_cls: The domain model type which will be persisted.
        :param persistence_cls: The SQL model type which will be persisted.

        """
        self._session = session
        self._persistence_cls = persistence_cls
        self._domain_cls = domain_cls

    async def get_by_pk(
        self, pk: UUID4, preload: list[str] | None = None
    ) -> GenericDomainModelType | None:
        """
        Get a record using its primary key.

        :param pk: The primary key to use to look up the record.
        :param preload: A list of attributes to preload using a join.

        :return: Domain model instance or None if not found.

        """
        options = []
        if preload:
            for p in preload:
                relationship = getattr(self._persistence_cls, p)
                options.append(joinedload(relationship))
        result = await self._session.get(self._persistence_cls, pk, options=options)
        if not result:
            return None
        return await result.to_domain(preload=preload)

    async def update_by_pk(self, pk: UUID4, **kwargs: object) -> GenericDomainModelType:
        """
        Update a record using its primary key.

        :param pk: The primary key to use to look up the record.
        :param kwargs: The attributes to update.

        :return: Domain model instance of the updated record.

        """
        persistence = await self._session.get(self._persistence_cls, pk)
        if not persistence:
            msg = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise RuntimeError(msg)

        # Check if key is in the persistence model.
        for key, value in kwargs.items():
            setattr(persistence, key, value)

        await self._session.flush()
        await self._session.refresh(persistence)
        return await persistence.to_domain()

    async def delete_by_pk(self, pk: UUID4) -> None:
        """
        Delete a record using its primary key.

        :param pk: The primary key to use to look up the record.

        """
        persistence = await self._session.get(self._persistence_cls, pk)
        if not persistence:
            msg = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise RuntimeError(msg)

        await self._session.delete(persistence)
        await self._session.flush()

    async def add(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Add a record to the repository.

        :param record: The record to be persisted.

        :return: Domain model instance of the persisted record.

        Note:
        This only adds a record to the session and flushes it. To persist the
        record after this transaction you will need to commit the session
        (generally through the unit of work).

        """
        persistence = await self._persistence_cls.from_domain(record)
        self._session.add(persistence)
        await self._session.flush()
        await self._session.refresh(persistence)
        return await persistence.to_domain()

    async def merge(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Merge a record into the repository.

        If the record already exists in the database based on the PK, it will be
        updated. If it does not exist, it will be added.
        See also: https://docs.sqlalchemy.org/en/20/orm/session_state_management.html#merge-tips

        :param record: The record to be persisted.

        :return: Domain model instance of the persisted record.

        """
        persistence = await self._persistence_cls.from_domain(record)
        persistence = await self._session.merge(persistence)
        await self._session.flush()
        await self._session.refresh(persistence)
        return await persistence.to_domain()
