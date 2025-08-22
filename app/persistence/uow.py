"""The unit of work manages the session transaction lifecycle."""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Final, Self

from opentelemetry import trace

from app.core.exceptions import IntegrityError, NotFoundError
from app.core.telemetry.attributes import set_span_status
from app.core.telemetry.logger import get_logger
from app.domain.imports.repository import (
    ImportBatchRepositoryBase,
    ImportRecordRepositoryBase,
    ImportResultRepositoryBase,
)
from app.domain.references.repository import (
    BatchEnhancementRequestRepositoryBase,
    EnhancementRepositoryBase,
    ExternalIdentifierRepositoryBase,
    PendingEnhancementRepositoryBase,
    ReferenceRepositoryBase,
    RobotAutomationRepositoryBase,
    RobotEnhancementBatchRepositoryBase,
)
from app.domain.robots.repository import (
    RobotRepositoryBase,
)
from app.persistence.repository import GenericAsyncRepository

logger = get_logger(__name__)


class AsyncUnitOfWorkBase(AbstractAsyncContextManager, ABC):
    """An asynchronous context manager which handles the persistence lifecyle."""

    imports: ImportRecordRepositoryBase
    batches: ImportBatchRepositoryBase
    results: ImportResultRepositoryBase
    references: ReferenceRepositoryBase
    external_identifiers: ExternalIdentifierRepositoryBase
    enhancements: EnhancementRepositoryBase
    batch_enhancement_requests: BatchEnhancementRequestRepositoryBase
    robots: RobotRepositoryBase
    robot_automations: RobotAutomationRepositoryBase
    pending_enhancements: PendingEnhancementRepositoryBase
    robot_enhancement_batches: RobotEnhancementBatchRepositoryBase

    _protected_attrs: Final[set[str]] = {
        "imports",
        "batches",
        "results",
        "references",
        "external_identifiers",
        "enhancements",
        "batch_enhancement_requests",
        "robots",
        "robot_automations",
        "pending_enhancements",
        "robot_enhancement_batches",
    }

    def __init__(self) -> None:
        """
        Initialize tracking of UOW instance.

        The _is_active logic ensures that the unit of work is not re-entered in
        a nested fashion.
        """
        self._is_active = False

    def __getattribute__(self, name: str) -> GenericAsyncRepository:
        """Protect access to repositories unless UoW is active."""
        protected = object.__getattribute__(self, "_protected_attrs")
        if name not in protected:
            return object.__getattribute__(self, name)
        is_active = object.__getattribute__(self, "_is_active")
        if not is_active:
            msg = (
                "Unit of work is not active. "
                "Make sure you are in a decorated function."
            )
            raise RuntimeError(msg)
        return object.__getattribute__(self, name)

    async def __aenter__(self) -> Self:
        """Set up the unit of work, including any repositories or sessions."""
        if self._is_active:
            msg = """
            Unit of work is already active.

            This is likely due to a nested decorator being used
            incorrectly. Ensure that the unit of work is not being
            re-entered in a nested fashion, i.e. by calling a decorated
            function from inside another decorated function.
            """
            raise RuntimeError(msg)
        self._is_active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Clean up any connections and rollback if an exception has been raised."""
        if exc_value:
            if exc_type in (IntegrityError, NotFoundError):
                # IntegrityError and NotFoundError are relatively expected exceptions
                # that don't require a full stack trace in the logs. It can still be
                # seen in the trace span.
                logger.warning(
                    "Rolling back unit of work.",
                    exc_type=exc_type,
                )
            else:
                logger.exception("Rolling back unit of work.")
            set_span_status(trace.StatusCode.ERROR, str(exc_value), exc_value)
            await self.rollback()
        else:
            set_span_status(trace.StatusCode.OK)
        self._is_active = False

    @abstractmethod
    async def rollback(self) -> None:
        """Disgard any uncommitted changes in the unit of work."""
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        """Commit any transactions opened as part of the unit of work."""
        raise NotImplementedError
