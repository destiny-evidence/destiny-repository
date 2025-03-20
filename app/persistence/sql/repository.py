"""Generic repositories define expected functionality."""

from abc import ABC
from typing import TypeVar

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlmodel import SQLModel

from app.persistence.repository import GenericAsyncRepository

T = TypeVar("T", bound=SQLModel)


class GenericAsyncSqlRepository(GenericAsyncRepository[T], ABC):
    """A generic implementation of a repository backed by SQLAlchemy."""

    _session: AsyncSession
    _model_cls: type[T]

    def __init__(self, session: AsyncSession, model_cls: type[T]) -> None:
        """
        Initialize the repository.

        Args:
        - session (AsyncSession): The current active database session.
        - model_cls (type[T]): The class of model which will be persisted.

        """
        self._session = session
        self._model_cls = model_cls

    async def get_by_pk(self, pk: UUID4, preload: list[str] | None = None) -> T | None:
        """
        Get a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.
        - preload (list[str]): A list of attributes to preload using a join.

        """
        options = []
        if preload:
            for p in preload:
                relationship = getattr(self._model_cls, p)
                options.append(joinedload(relationship))
        return await self._session.get(self._model_cls, pk, options=options)

    async def add(self, record: T) -> T:
        """
        Add a record to the repository.

        Args:
        - record (T): The record to be persisted.

        Note:
        This only adds a record to the session and flushes it. To persist the
        record after this transaction you will need to commit the session
        (probably the job of the service through the unit of work.)

        """
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record
