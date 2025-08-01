"""Functions for tracing blob functionality."""

import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import ParamSpec, TypeVar, cast

from opentelemetry import trace

from app.core.telemetry.attributes import Attributes
from app.persistence.blob.models import BlobStorageFile

T = TypeVar("T")
P = ParamSpec("P")


def _extract_blob_file_from_args(*args: object, **kwargs: object) -> BlobStorageFile:
    """Extract BlobStorageFile from function arguments."""
    file = cast(
        BlobStorageFile,
        kwargs.get(
            "file",
            next((arg for arg in args if isinstance(arg, BlobStorageFile)), None),
        ),
    )
    if not file:
        msg = "No BlobStorageFile found in arguments for tracing."
        raise RuntimeError(msg)
    return file


def _create_span_attributes(func: Callable, file: BlobStorageFile, action: str) -> dict:
    """Create standard span attributes for blob operations."""
    return {
        Attributes.CODE_FUNCTION_NAME: func.__qualname__,
        Attributes.DB_COLLECTION_NAME: f"{file.container}/{file.path}",
        Attributes.DB_OPERATION_NAME: action,
        Attributes.DB_PK: file.filename,
        Attributes.DB_SYSTEM_NAME: file.location,
    }


def trace_blob_client_method(
    tracer: trace.Tracer,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorate a repository method with a given tracer."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        """Decorate repository methods with standard telemetry tracing attributes."""

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            action = func.__name__.replace("_", " ").capitalize()
            file = _extract_blob_file_from_args(*args, **kwargs)

            # Start the span and execute the original function
            with tracer.start_as_current_span(
                f"BLOB ({file.location}): {action}",
                attributes=_create_span_attributes(func, file, action),
            ):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def trace_blob_client_generator(
    tracer: trace.Tracer,
) -> Callable[
    [Callable[P, AsyncGenerator[T, None]]], Callable[P, AsyncGenerator[T, None]]
]:
    """Decorate a repository generator method with a given tracer."""

    def decorator(
        func: Callable[P, AsyncGenerator[T, None]],
    ) -> Callable[P, AsyncGenerator[T, None]]:
        """Decorate repository generator methods with standard telemetry tracing."""

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[T, None]:
            action = func.__name__.replace("_", " ").capitalize()
            file = _extract_blob_file_from_args(*args, **kwargs)

            # Start the span and yield from the original generator
            with tracer.start_as_current_span(
                f"BLOB ({file.location}): {action}",
                attributes=_create_span_attributes(func, file, action),
            ):
                async for item in func(*args, **kwargs):
                    yield item

        return wrapper

    return decorator
