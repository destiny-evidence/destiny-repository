"""The unit of work manages the session transaction lifecycle."""

import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from types import TracebackType
from typing import TYPE_CHECKING, ParamSpec, Self, TypeVar, cast

from elasticsearch import AsyncElasticsearch
from opentelemetry import trace

from app.core.exceptions import UOWError
from app.core.telemetry.attributes import Attributes
from app.domain.references.repository import (
    ReferenceESRepository,
    RobotAutomationESRepository,
)
from app.persistence.uow import AsyncUnitOfWorkBase

if TYPE_CHECKING:
    from app.domain.service import GenericService

tracer = trace.get_tracer(__name__)


class AsyncESUnitOfWork(AsyncUnitOfWorkBase):
    """
    A unit of work for imports backed by Elasticsearch.

    This is a stub and can be implemented later if custom transaction-style logic is
    desired. Elasticsearch does not natively support transaction boundaries.
    """

    client: AsyncElasticsearch

    references: ReferenceESRepository
    robot_automations: RobotAutomationESRepository

    def __init__(self, client: AsyncElasticsearch) -> None:
        """Initialize the unit of work with a client."""
        self.client = client
        super().__init__()

    async def __aenter__(self) -> Self:
        """Set up the Elasticsearch repositories and open the session."""
        self.references = ReferenceESRepository(self.client)
        self.robot_automations = RobotAutomationESRepository(self.client)

        return await super().__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session and rollback if an exception has been raised."""
        await super().__aexit__(exc_type, exc_value, traceback)

    async def rollback(self) -> None:
        """Roll back the session."""

    async def commit(self) -> None:
        """Commit the session."""


T = TypeVar("T")
P = ParamSpec("P")


def unit_of_work(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Handle unit of work lifecycle with a decorator."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        svc = cast("GenericService", args[0])
        if not svc.es_uow:
            msg = "Elasticsearch unit of work is not initialized."
            raise UOWError(msg)
        with tracer.start_as_current_span(
            "ES Unit of Work", attributes={Attributes.DB_SYSTEM_NAME: "ES"}
        ):
            async with svc.es_uow:
                result: T = await fn(*args, **kwargs)
                await svc.es_uow.commit()
                return result

    return wrapper


def generator_unit_of_work(
    fn: Callable[P, AsyncGenerator[T, None]],
) -> Callable[P, AsyncGenerator[T, None]]:
    """Handle unit of work lifecycle with a decorator for AsyncGenerator."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[T, None]:
        svc = cast("GenericService", args[0])
        if not svc.es_uow:
            msg = "Elasticsearch unit of work is not initialized."
            raise UOWError(msg)

        with tracer.start_as_current_span(
            "ES Unit of Work", attributes={Attributes.DB_SYSTEM_NAME: "ES"}
        ):
            async with svc.es_uow:
                async for item in fn(*args, **kwargs):
                    yield item
                await svc.es_uow.commit()

    return wrapper
