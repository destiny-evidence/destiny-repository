"""The unit of work manages the session transaction lifecycle."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports.repository import (
    ImportBatchSQLRepository,
    ImportRecordSQLRepository,
    ImportResultSQLRepository,
)
from app.persistence.uow import AsyncUnitOfWorkBase


class AsyncSqlUnitOfWork(AsyncUnitOfWorkBase):
    """A unit of work for imports backed by SQLAlchemy."""

    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the unit of work with a session."""
        self.session = session

    async def __aenter__(self) -> Self:
        """Set up the SQL repositories and open the session."""
        self.imports = ImportRecordSQLRepository(self.session)
        self.batches = ImportBatchSQLRepository(self.session)
        self.results = ImportResultSQLRepository(self.session)

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
