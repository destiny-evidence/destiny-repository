"""Pydantic models used to validate reference data."""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.references.models.models import Visibility
from app.utils.types import JSON


class ReferenceFileInputValidator(BaseModel):
    """Validator for the top-level schema of a reference entry from a file."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[JSON] = Field(min_length=1)
    enhancements: list[JSON] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
