"""Exception handlers for the repository API."""

from collections.abc import Sequence
from uuid import UUID

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.exceptions import (
    ESMalformedDocumentError,
    ESNotFoundError,
    ESQueryError,
    IntegrityError,
    InvalidPayloadError,
    NotFoundError,
    ParseError,
    SDKToDomainError,
    SQLIntegrityError,
    SQLNotFoundError,
)


class APIExceptionContent(BaseModel):
    """Return model for API exception content."""

    detail: str = Field(description="Details about the error.")


class APIExceptionResponse(JSONResponse):
    """Return model for API 4XX codes."""

    def __init__(self, status_code: int, content: APIExceptionContent) -> None:
        """Initialize the response with JSON content."""
        super().__init__(status_code=status_code, content=jsonable_encoder(content))


async def not_found_exception_handler(
    request: Request,
    exception: NotFoundError,
) -> APIExceptionResponse:
    """
    Exception handler for when an object cannot be found.

    If the object is part of the API resource (eg, the lookup ID was in the URL),
    it returns a 404.
    Otherwise, it returns a 422.
    """
    if isinstance(exception, SQLNotFoundError | ESNotFoundError):
        content = APIExceptionContent(
            detail=(
                f"{exception.lookup_model} with "
                f"{exception.lookup_type} {exception.lookup_value} does not exist."
            )
        )
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        if (
            isinstance(exception.lookup_value, UUID | str | int)
            and str(exception.lookup_value) in request.url.path
        ):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exception.lookup_value, Sequence) and request.method == "GET":
            # Best-efforts attempt on search lookups
            # We don't really know how these will look so this may need revisiting
            query_params = {
                param.casefold() for param in request.query_params.values() if param
            }
            lookup_params = {
                str(param).casefold() for param in exception.lookup_value if param
            }
            if query_params == lookup_params:
                status_code = status.HTTP_404_NOT_FOUND
    else:
        status_code = status.HTTP_404_NOT_FOUND
        content = APIExceptionContent(detail=exception.detail)

    return APIExceptionResponse(
        status_code=status_code,
        content=content,
    )


async def integrity_exception_handler(
    _request: Request,
    exception: IntegrityError,
) -> APIExceptionResponse:
    """Exception handler to return 409 responses when an IntegrityError is thrown."""
    if isinstance(exception, SQLIntegrityError):
        content = APIExceptionContent(
            detail=f"{exception.detail} {exception.collision}"
        )
    else:
        content = APIExceptionContent(detail=exception.detail)

    return APIExceptionResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=content,
    )


# NB we don't handle DomainToSDKError as the default 500 is most appropriate.
async def sdk_to_domain_exception_handler(
    _request: Request,
    exception: SDKToDomainError,
) -> APIExceptionResponse:
    """Return unprocessable entity response when sdk -> domain conversion fails."""
    # Probably want to reduce the amount of information we're giving back here.
    return APIExceptionResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=APIExceptionContent(detail=exception.errors),
    )


async def invalid_payload_exception_handler(
    _request: Request,
    exception: InvalidPayloadError,
) -> APIExceptionResponse:
    """Return unprocessable entity response when the payload is invalid."""
    return APIExceptionResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=APIExceptionContent(detail=exception.detail),
    )


async def es_exception_handler(
    _request: Request,
    exception: ESQueryError | ESMalformedDocumentError,
) -> APIExceptionResponse:
    """
    Return unprocessable entity response when an Elasticsearch operation fails.

    This is generally raised on incorrect query structures for percolation and
    searching.
    """
    return APIExceptionResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=APIExceptionContent(detail=exception.detail),
    )


async def parse_error_exception_handler(
    _request: Request,
    exception: ParseError,
) -> APIExceptionResponse:
    """Return bad request response when a parsing error occurs."""
    return APIExceptionResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=APIExceptionContent(detail=exception.detail),
    )
