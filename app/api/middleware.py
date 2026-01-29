"""Middleware for the repository API."""

from collections.abc import Awaitable, Callable
from uuid import uuid7

from fastapi import status
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, unbind_contextvars

from app.core.telemetry.logger import get_logger


class LoggerMiddleware(BaseHTTPMiddleware):
    """
    Middleware class to log requests and responses.

    This middleware logs all incoming requests with contextual information
    and categorizes responses based on their status codes.
    """

    def __init__(self, app: Starlette) -> None:
        """
        Initialize the logger middleware.

        Args:
            app: The Starlette application instance.

        """
        super().__init__(app)
        self.logger = get_logger(__name__)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process the request and response with logging.

        Args:
            request: The incoming request.
            call_next: The next middleware or route handler.

        Returns:
            The response from the next middleware or route handler.

        """
        bind_contextvars(
            path=request.url.path,
            method=request.method,
            client_host=request.client and request.client.host,
            request_id=str(uuid7()),
        )

        try:
            response = await call_next(request)
            bind_contextvars(status_code=response.status_code)

            if (
                status.HTTP_400_BAD_REQUEST
                <= response.status_code
                < status.HTTP_500_INTERNAL_SERVER_ERROR
            ):
                self.logger.warning("Client error")
            elif response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                self.logger.error("Server error")
            else:
                self.logger.info("OK")

        except Exception:
            self.logger.exception("Unhandled exception in request")
            unbind_contextvars(
                "path", "method", "client_host", "request_id", "status_code"
            )
            raise
        else:
            unbind_contextvars(
                "path", "method", "client_host", "request_id", "status_code"
            )
            return response
