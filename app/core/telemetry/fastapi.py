"""Middleware for OpenTelemetry tracing in FastAPI applications."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from opentelemetry import trace
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match
from structlog import get_logger
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
)
from structlog.stdlib import BoundLogger

from app.core.telemetry.attributes import Attributes

logger: BoundLogger = get_logger(__name__)


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

        if request.url.query:
            # Add individual query parameters as attributes using FastAPI
            if current_span.is_recording():
                for key, value in request.query_params.items():
                    current_span.set_attribute(
                        f"{Attributes.HTTP_REQUEST_QUERY_PARAMS}.{key}", value
                    )
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
                bind_contextvars(**scope["path_params"])

        try:
            result = await call_next(request)
        except Exception:
            clear_contextvars()
            raise
        else:
            # This is guaranteed to be the outermost middleware so we clear all context
            clear_contextvars()
            return result
