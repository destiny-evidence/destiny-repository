"""Standard API response models."""

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class StringResponseContent(BaseModel):
    """Model for simple string API responses."""

    detail: str


class APIExceptionContent(BaseModel):
    """Return model for API exception content."""

    detail: str = Field(description="Details about the error.")


class APIExceptionResponse(JSONResponse):
    """Return model for API 4XX codes."""

    def __init__(self, status_code: int, content: APIExceptionContent) -> None:
        """Initialize the response with JSON content."""
        super().__init__(status_code=status_code, content=jsonable_encoder(content))
