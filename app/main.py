"""Main module for the DESTINY Climate and Health Repository API."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, status

from app.core.config import get_settings
from app.core.logger import configure_logger, get_logger
from app.domain.imports.routes import router as import_router
from app.persistence.sql.session import db_manager
from app.utils.healthcheck import router as healthcheck_router

settings = get_settings()
logger = get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Lifespan hook for FastAPI."""
    db_manager.init(str(settings.db_url))
    yield
    await db_manager.close()


app = FastAPI(title="DESTINY Climate and Health Repository", lifespan=lifespan)

app.include_router(import_router)
app.include_router(healthcheck_router)

configure_logger()


@app.middleware("http")
async def logger_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """
    Middleware to log requests and responses.

    Args:
        request (Request): The incoming request.
        call_next: The next middleware or route handler.

    Returns:
        Response: The response from the next middleware or route handler.

    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        path=request.url.path,
        method=request.method,
        client_host=request.client and request.client.host,
        request_id=str(uuid.uuid4()),
    )

    try:
        response = await call_next(request)
        structlog.contextvars.bind_contextvars(status_code=response.status_code)

        if (
            status.HTTP_400_BAD_REQUEST
            <= response.status_code
            < status.HTTP_500_INTERNAL_SERVER_ERROR
        ):
            logger.warning("Client error")
        elif response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("Server error")
        else:
            logger.info("OK")

    except Exception:
        logger.exception("Unhandled exception in request")
        raise
    else:
        return response


@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint for the API.

    Returns:
        dict[str, str]: A simple message.

    """
    return {"message": "Hello World"}
