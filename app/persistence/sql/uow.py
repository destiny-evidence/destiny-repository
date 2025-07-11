"""The unit of work manages the session transaction lifecycle."""

import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import suppress
from types import TracebackType
from typing import TYPE_CHECKING, ParamSpec, Self, TypeVar, cast

from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.domain.imports.repository import (
    ImportBatchSQLRepository,
    ImportRecordSQLRepository,
    ImportResultSQLRepository,
)
from app.domain.references.repository import (
    BatchEnhancementRequestSQLRepository,
    EnhancementRequestSQLRepository,
    EnhancementSQLRepository,
    ExternalIdentifierSQLRepository,
    ReferenceSQLRepository,
    RobotAutomationSQLRepository,
)
from app.domain.robots.repository import (
    RobotSQLRepository,
)
from app.persistence.uow import AsyncUnitOfWorkBase

if TYPE_CHECKING:
    from app.domain.service import GenericService
logger = get_logger()


class AsyncSqlUnitOfWork(AsyncUnitOfWorkBase):
    """A unit of work for imports backed by SQLAlchemy."""

    session: AsyncSession

    imports: ImportRecordSQLRepository
    batches: ImportBatchSQLRepository
    results: ImportResultSQLRepository
    references: ReferenceSQLRepository
    external_identifiers: ExternalIdentifierSQLRepository
    enhancements: EnhancementSQLRepository
    enhancement_requests: EnhancementRequestSQLRepository
    batch_enhancement_requests: BatchEnhancementRequestSQLRepository
    robots: RobotSQLRepository
    robot_automations: RobotAutomationSQLRepository

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
        self.enhancement_requests = EnhancementRequestSQLRepository(self.session)
        self.batch_enhancement_requests = BatchEnhancementRequestSQLRepository(
            self.session
        )
        self.robots = RobotSQLRepository(self.session)
        self.robot_automations = RobotAutomationSQLRepository(self.session)

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
        with suppress(PendingRollbackError):
            # An SQL-layer error has already rolled back the session
            await self.session.rollback()

    async def commit(self) -> None:
        """Commit the session."""
        try:
            await self.session.commit()
        except PendingRollbackError:
            # An SQL-layer error has caused the session to be rolled back.
            # We'd only get this far if said error was caught by the service,
            # hence why this is just a warning.
            logger.warning(
                "Session commit failed; this session has already been rolled back."
            )


T = TypeVar("T")
P = ParamSpec("P")


def unit_of_work(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Handle unit of work lifecycle with a decorator."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        svc = cast("GenericService", args[0])
        async with svc.sql_uow:
            result: T = await fn(*args, **kwargs)
            await svc.sql_uow.commit()
            return result

    return wrapper


def generator_unit_of_work(
    fn: Callable[P, AsyncGenerator[T, None]],
) -> Callable[P, AsyncGenerator[T, None]]:
    """Handle unit of work lifecycle with a decorator for AsyncGenerator."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[T, None]:
        svc = cast("GenericService", args[0])
        async with svc.sql_uow:
            async for item in fn(*args, **kwargs):
                yield item
            await svc.sql_uow.commit()

    return wrapper
