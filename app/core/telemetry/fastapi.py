"""Middleware for OpenTelemetry tracing in FastAPI applications."""

from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Request, Response
from opentelemetry import trace
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match
from structlog.contextvars import (
    bind_contextvars,
    bound_contextvars,
    unbind_contextvars,
)

from app.core.telemetry.attributes import Attributes
from app.core.telemetry.logger import get_logger

logger = get_logger(__name__)


class FastAPITracingMiddleware(BaseHTTPMiddleware):
    """Middleware class to add query and path parameters to OpenTelemetry spans."""

    def __init__(self, app: Starlette) -> None:
        """
        Initialize the tracing middleware.

        Args:
            app: The Starlette application instance.

        """
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process the request and add tracing attributes.

        Args:
            request: The incoming request.
            call_next: The next middleware or route handler.

        Returns:
            The response from the next middleware or route handler.

        """
        current_span = trace.get_current_span()
        contextvars: set[str] = set()
        if request.url.query:
            # Add individual query parameters as attributes using FastAPI
            if current_span.is_recording():
                for key, value in request.query_params.items():
                    current_span.set_attribute(
                        f"{Attributes.HTTP_REQUEST_QUERY_PARAMS}.{key}", value
                    )
            contextvars |= request.query_params.keys()
            bind_contextvars(**request.query_params)

        # Can't access path parameters directly in middleware.
        # This is what starlette does internally.
        # https://github.com/fastapi/fastapi/issues/861
        # https://github.com/encode/starlette/blob/5c43dde0ec0917673bb280bcd7ab0c37b78061b7/starlette/routing.py#L544
        routes = request.app.router.routes
        for route in routes:
            match, scope = route.matches(request)
            if match == Match.FULL:
                if current_span.is_recording():
                    for key, value in scope["path_params"].items():
                        current_span.set_attribute(
                            f"{Attributes.HTTP_REQUEST_PATH_PARAMS}.{key}", str(value)
                        )
                contextvars |= scope["path_params"].keys()
                bind_contextvars(**scope["path_params"])

        try:
            result = await call_next(request)
        except Exception:
            unbind_contextvars(*contextvars)
            raise
        else:
            unbind_contextvars(*contextvars)
            return result


class PayloadAttributeTracer:
    """Context manager to log and trace an attribute from the request payload."""

    def __init__(self, attribute: str) -> None:
        """
        Initialize the tracer with the attribute to trace.

        Args:
            attribute: The attribute name to trace from the request payload.

        """
        self.attribute = attribute

    async def __call__(self, request: Request) -> AsyncGenerator[None, None]:
        """
        Add the specified payload attribute as an OpenTelemetry span attribute.

        Args:
            request: The incoming request.

        Yields:
            None, but sets the attribute on the current span.

        """
        try:
            body: dict = await request.json()
        except ValueError:
            logger.debug("Failed to parse request body as JSON")
            yield
        else:
            current_span = trace.get_current_span()
            value = body.get(self.attribute)
            if value:
                current_span.set_attribute(
                    f"{Attributes.HTTP_REQUEST_BODY_PARAMS}.{self.attribute}", value
                )
                with bound_contextvars(**{self.attribute: value}):
                    yield
            else:
                yield
