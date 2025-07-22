"""Exception handlers for the repository API."""

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ESMalformedDocumentError,
    IntegrityError,
    InvalidPayloadError,
    NotFoundError,
    SDKToDomainError,
    SQLIntegrityError,
    SQLNotFoundError,
)


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


# NB we don't handle DomainToSDKError as the default 500 is most appropriate.
async def sdk_to_domain_exception_handler(
    _request: Request,
    exception: SDKToDomainError,
) -> JSONResponse:
    """Return unprocessable entity response when sdk -> domain conversion fails."""
    # Probably want to reduce the amount of information we're giving back here.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exception.errors}),
    )


async def invalid_payload_exception_handler(
    _request: Request,
    exception: InvalidPayloadError,
) -> JSONResponse:
    """Return unprocessable entity response when the payload is invalid."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exception.detail}),
    )


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
