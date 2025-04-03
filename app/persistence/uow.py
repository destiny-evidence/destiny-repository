"""The unit of work manages the session transaction lifecycle."""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Self

from app.domain.imports.repository import (
    ImportBatchRepositoryBase,
    ImportRecordRepositoryBase,
    ImportResultRepositoryBase,
)
from app.domain.references.repository import (
    EnhancementRepositoryBase,
    ExternalIdentifierRepositoryBase,
    ReferenceRepositoryBase,
)


class AsyncUnitOfWorkBase(AbstractAsyncContextManager, ABC):
    """An asynchronous context manager which handles the persistence lifecyle."""

    imports: ImportRecordRepositoryBase
    batches: ImportBatchRepositoryBase
    results: ImportResultRepositoryBase
    references: ReferenceRepositoryBase
    external_identifiers: ExternalIdentifierRepositoryBase
    enhancements: EnhancementRepositoryBase

    def __init__(self) -> None:
        """
        Initialize tracking of UOW instance.

        The _is_active logic ensures that the unit of work is not re-entered in
        a nested fashion.
        """
        self._is_active = False

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
        if exc_type:
            await self.rollback()
        self._is_active = False

    @abstractmethod
    async def rollback(self) -> None:
        """Disgard any uncommitted changes in the unit of work."""
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        """Commit any transactions opened as part of the unit of work."""
        raise NotImplementedError
