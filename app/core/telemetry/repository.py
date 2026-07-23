"""Functions for tracing repository functionality."""

import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

from opentelemetry import trace
from opentelemetry.trace import Span

from app.core.telemetry.attributes import Attributes

if TYPE_CHECKING:
    from app.persistence.repository import GenericAsyncRepository

T = TypeVar("T")
Y = TypeVar("Y")
P = ParamSpec("P")


def _span_context(
    tracer: trace.Tracer,
    func: Callable[..., object],
    args: tuple[object, ...],
) -> AbstractContextManager[Span]:
    """Build the span for a repository method from its name and its repository."""
    repository = cast("GenericAsyncRepository", args[0])
    method_parts = func.__name__.split("_")
    repository_implementation = repository._persistence_cls.__name__  # noqa: SLF001
    verb = method_parts[0]
    span_name = f"{repository.system}: {verb.capitalize()} {repository_implementation}"
    if len(method_parts) > 1:
        span_name = f"{span_name}.{'_'.join(method_parts[1:])}"
    return tracer.start_as_current_span(
        span_name,
        attributes={
            Attributes.CODE_FUNCTION_NAME: func.__qualname__,
            Attributes.DB_COLLECTION_NAME: repository_implementation,
            Attributes.DB_OPERATION_NAME: verb,
            Attributes.DB_SYSTEM_NAME: repository.system,
        },
    )


def trace_repository_method(
    tracer: trace.Tracer,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorate an async repository method with a given tracer."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with _span_context(tracer, func, args):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def trace_repository_generator(
    tracer: trace.Tracer,
) -> Callable[
    [Callable[P, AsyncGenerator[Y, None]]], Callable[P, AsyncGenerator[Y, None]]
]:
    """Trace an async-generator repository method, spanning the full iteration."""

    def decorator(
        func: Callable[P, AsyncGenerator[Y, None]],
    ) -> Callable[P, AsyncGenerator[Y, None]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[Y, None]:
            agen = func(*args, **kwargs)
            with _span_context(tracer, func, args):
                try:
                    async for item in agen:
                        yield item
                finally:
                    await agen.aclose()

        return wrapper

    return decorator
