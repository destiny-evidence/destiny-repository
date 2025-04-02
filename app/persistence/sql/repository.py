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
    ) -> GenericDomainModelType | None:
        """
        Get a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.
        - preload (list[str]): A list of attributes to preload using a join.

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

    async def add(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Add a record to the repository.

        Args:
        - record (T): The record to be persisted.

        Note:
        This only adds a record to the session and flushes it. To persist the
        record after this transaction you will need to commit the session
        (probably the job of the service through the unit of work.)

        """
        persistence = await self._persistence_cls.from_domain(record)
        self._session.add(persistence)
        await self._session.flush()
        await self._session.refresh(persistence)
        return await persistence.to_domain()
