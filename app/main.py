"""Main module for the DESTINY Climate and Health Repository API."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import (
    ESMalformedDocumentError,
    IntegrityError,
    InvalidPayloadError,
    NotFoundError,
    SDKToDomainError,
    SQLIntegrityError,
    SQLNotFoundError,
)
from app.core.logger import configure_logger, get_logger
from app.domain.imports.routes import router as import_router_v1
from app.domain.references.routes import robot_router as robot_router_v1
from app.domain.references.routes import router as reference_router_v1
from app.domain.robots.routes import router as robot_management_router_v1
from app.persistence.es.client import es_manager
from app.persistence.sql.session import db_manager
from app.tasks import broker
from app.utils.healthcheck import router as healthcheck_router_v1

settings = get_settings()
logger = get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Lifespan hook for FastAPI."""
    # TODO(Adam): implement similar pattern for blob storage  # noqa: TD003
    db_manager.init(settings.db_config, settings.app_name)
    await es_manager.init(settings.es_config)
    await broker.startup()

    yield

    await broker.shutdown()
    await db_manager.close()
    await es_manager.close()


app = FastAPI(title="DESTINY Climate and Health Repository", lifespan=lifespan)

api_v1 = APIRouter(prefix="/v1", tags=["v1"])
api_v1.include_router(import_router_v1)
api_v1.include_router(reference_router_v1)
api_v1.include_router(robot_router_v1)
api_v1.include_router(robot_management_router_v1)
api_v1.include_router(healthcheck_router_v1)
app.include_router(api_v1)

configure_logger(rich_rendering=settings.running_locally)


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


@app.exception_handler(NotFoundError)
async def not_found_exception_handler(
    _request: Request,
    exception: NotFoundError,
) -> JSONResponse:
    """Exception handler to return 404 responses when NotFoundError is thrown."""
    if isinstance(exception, SQLNotFoundError):
        content = {
            "detail": (
                f"{exception.lookup_model} with "
                f"{exception.lookup_type} {exception.lookup_value} does not exist."
            )
        }
    else:
        content = {"detail": exception.detail}

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=content,
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(
    _request: Request,
    exception: IntegrityError,
) -> JSONResponse:
    """Exception handler to return 409 responses when an IntegrityError is thrown."""
    if isinstance(exception, SQLIntegrityError):
        content = {"detail": f"{exception.detail} {exception.collision}"}
    else:
        content = {"detail": exception.detail}

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=content,
    )


@app.exception_handler(SDKToDomainError)
async def sdk_to_domain_exception_handler(
    _request: Request,
    exception: SDKToDomainError,
) -> JSONResponse:
    """Return unprocessable entity response when sdk -> domain converstion fails."""
    # Probably want to reduce the amount of information we're giving back here.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exception.errors}),
    )


@app.exception_handler(InvalidPayloadError)
async def enhance_wrong_reference_exception_handler(
    _request: Request,
    exception: InvalidPayloadError,
) -> JSONResponse:
    """Return unprocessable entity response when the payload is invalid."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exception.detail}),
    )


@app.exception_handler(ESMalformedDocumentError)
async def es_malformed_exception_handler(
    _request: Request,
    exception: ESMalformedDocumentError,
) -> JSONResponse:
    """
    Return unprocessable entity response when an Elasticsearch document is malformed.

    This is generally raised on incorrect percolation queries attempting to be saved.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=jsonable_encoder({"detail": exception.detail}),
    )


@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint for the API.

    Returns:
        dict[str, str]: A simple message.

    """
    return {"message": "Hello World"}
