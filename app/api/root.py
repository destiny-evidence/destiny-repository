"""Root API router for the repository API."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import APIRouter, FastAPI
from fastapi.middleware import Middleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.api.exception_handlers import (
    es_malformed_exception_handler,
    integrity_exception_handler,
    invalid_payload_exception_handler,
    not_found_exception_handler,
    sdk_to_domain_exception_handler,
)
from app.api.middleware import LoggerMiddleware
from app.core.exceptions import (
    ESMalformedDocumentError,
    IntegrityError,
    InvalidPayloadError,
    NotFoundError,
    SDKToDomainError,
)
from app.core.logger import get_logger
from app.domain.imports.routes import router as import_router_v1
from app.domain.references.routes import (
    enhancement_request_router as enhancement_request_router_v1,
)
from app.domain.references.routes import reference_router as reference_router_v1
from app.domain.robots.routes import router as robot_management_router_v1
from app.system.routes import router as system_utilities_router_v1

logger = get_logger()


def create_v1_router() -> APIRouter:
    """Create the v1 API router with all domain-specific routers."""
    api_v1 = APIRouter(prefix="/v1", tags=["v1"])
    api_v1.include_router(import_router_v1)
    api_v1.include_router(enhancement_request_router_v1)
    api_v1.include_router(reference_router_v1)
    api_v1.include_router(robot_management_router_v1)
    api_v1.include_router(system_utilities_router_v1)
    return api_v1


def register_api(
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager],
) -> FastAPI:
    """Register the API routers and configure the FastAPI application."""
    app = FastAPI(
        title="DESTINY Climate and Health Repository",
        lifespan=lifespan,
        middleware=[Middleware(LoggerMiddleware)],
        exception_handlers={
            NotFoundError: not_found_exception_handler,
            IntegrityError: integrity_exception_handler,
            SDKToDomainError: sdk_to_domain_exception_handler,
            InvalidPayloadError: invalid_payload_exception_handler,
            ESMalformedDocumentError: es_malformed_exception_handler,
        },
    )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Hello World"}

    app.include_router(create_v1_router())

    FastAPIInstrumentor().instrument_app(app)

    return app
