"""The unit of work manages the session transaction lifecycle."""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.imports import (
    ImportBatchRepository,
    ImportBatchRepositoryBase,
    ImportRepository,
    ImportRepositoryBase,
)


class AsyncUnitOfWorkBase(AbstractAsyncContextManager, ABC):
    """An asynchronous context manager which handles the persistence lifecyle."""

    imports: ImportRepositoryBase
    batches: ImportBatchRepositoryBase

    async def __aenter__(self) -> Self:
        """Set up the unit of work, including any repositories or sessions."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Clean up any connections and rollback if an exception has been raised."""
        if exc_type:
            await self.rollback()

    @abstractmethod
    async def rollback(self) -> None:
        """Disgard any uncommitted changes in the unit of work."""
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        """Commit any transactions opened as part of the unit of work."""
        raise NotImplementedError


class AsyncSqlUnitOfWork(AsyncUnitOfWorkBase):
    """A unit of work for imports backed by SQLAlchemy."""

    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the unit of work with a session."""
        self.session = session

    async def __aenter__(self) -> Self:
        """Set up the repositories and open the session."""
        self.imports = ImportRepository(self.session)
        self.batches = ImportBatchRepository(self.session)

        return await super().__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session and rollback if an exception has been raised."""
        await super().__aexit__(exc_type, exc_value, traceback)
        await self.session.close()

    async def rollback(self) -> None:
        """Roll back the session."""
        await self.session.rollback()

    async def commit(self) -> None:
        """Commit the session."""
        await self.session.commit()
