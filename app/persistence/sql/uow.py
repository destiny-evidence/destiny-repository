"""The unit of work manages the session transaction lifecycle."""

import functools
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import ParamSpec, Self, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports.repository import (
    ImportBatchSQLRepository,
    ImportRecordSQLRepository,
    ImportResultSQLRepository,
)
from app.domain.references.repository import (
    EnhancementSQLRepository,
    ExternalIdentifierSQLRepository,
    ReferenceSQLRepository,
)
from app.persistence.uow import AsyncUnitOfWorkBase


class AsyncSqlUnitOfWork(AsyncUnitOfWorkBase):
    """A unit of work for imports backed by SQLAlchemy."""

    session: AsyncSession

    imports: ImportRecordSQLRepository
    batches: ImportBatchSQLRepository
    results: ImportResultSQLRepository
    references: ReferenceSQLRepository
    external_identifiers: ExternalIdentifierSQLRepository
    enhancements: EnhancementSQLRepository

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the unit of work with a session."""
        self.session = session
        super().__init__()

    async def __aenter__(self) -> Self:
        """Set up the SQL repositories and open the session."""
        self.imports = ImportRecordSQLRepository(self.session)
        self.batches = ImportBatchSQLRepository(self.session)
        self.results = ImportResultSQLRepository(self.session)
        self.references = ReferenceSQLRepository(self.session)
        self.external_identifiers = ExternalIdentifierSQLRepository(self.session)
        self.enhancements = EnhancementSQLRepository(self.session)

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


T = TypeVar("T")
P = ParamSpec("P")


def unit_of_work(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Handle unit of work lifecycle with a decorator."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        sql_uow: AsyncSqlUnitOfWork = args[0].sql_uow  # type:ignore[arg-type, attr-defined]
        async with sql_uow:
            result: T = await fn(*args, **kwargs)
            await sql_uow.commit()
            return result

    return wrapper
