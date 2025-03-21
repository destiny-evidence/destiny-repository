"""Generic repositories define expected functionality."""

from abc import ABC
from typing import Generic

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.persistence.generics import GenericDomainModelType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.generics import GenericSQLModelType, SQLDTOType


class GenericAsyncSqlRepository(
    GenericAsyncRepository[SQLDTOType, GenericDomainModelType],
    Generic[SQLDTOType, GenericDomainModelType, GenericSQLModelType],
    ABC,
):
    """A generic implementation of a repository backed by SQLAlchemy."""

    _session: AsyncSession
    _sql_cls: type[GenericSQLModelType]

    def __init__(
        self,
        session: AsyncSession,
        dto_cls: type[SQLDTOType],
        domain_cls: type[GenericDomainModelType],
        sql_cls: type[GenericSQLModelType],
    ) -> None:
        """
        Initialize the repository.

        Args:
        - session (AsyncSession): The current active database session.
        - _dto_cls (type[SQLDTO]): The SQLDTO of model which will be persisted.
        - _domain_cls (type[GenericDomainModelType]):
            The domain class of model which will be persisted.
        - _sql_cls (type[GenericSQLModelType]):
            The sql class of model which will be persisted.

        """
        self._session = session
        self._dto_cls = dto_cls
        self._domain_cls = domain_cls
        self._sql_cls = sql_cls

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
                relationship = getattr(self._sql_cls, p)
                options.append(joinedload(relationship))
        result = await self._session.get(self._sql_cls, pk, options=options)
        if not result:
            return None
        dto = await self._dto_cls.from_sql(result)
        return await dto.to_domain()

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
        dto = await self._dto_cls.from_domain(record)
        sql_record = await dto.to_sql()
        self._session.add(sql_record)
        await self._session.flush()
        await self._session.refresh(sql_record)
        dto = await self._dto_cls.from_sql(sql_record)
        return await dto.to_domain()
