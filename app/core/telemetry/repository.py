"""Functions for tracing repository functionality."""

import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

from opentelemetry import trace

from app.core.telemetry.attributes import Attributes

if TYPE_CHECKING:
    from app.persistence.repository import GenericAsyncRepository

T = TypeVar("T")
P = ParamSpec("P")


def trace_repository_method(
    tracer: trace.Tracer,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorate a repository method with a given tracer."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        """Decorate repository methods with standard telemetry tracing attributes."""

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            self = cast("GenericAsyncRepository", args[0])
            method_parts = func.__name__.split("_")

            verb = method_parts[0]

            span_name = (
                f"{self.system}: {verb.capitalize()} {self._persistence_cls.__name__}"
            )

            if len(method_parts) > 1:
                details = "_".join(method_parts[1:])
                span_name = f"{span_name}.{details}"

            # Start the span and execute the original function
            with tracer.start_as_current_span(
                span_name,
                attributes={
                    Attributes.CODE_FUNCTION_NAME: func.__qualname__,
                    Attributes.DB_COLLECTION_NAME: self._persistence_cls.__name__,
                    Attributes.DB_OPERATION_NAME: verb,
                    Attributes.DB_SYSTEM_NAME: self.system,
                },
            ):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
