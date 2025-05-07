"""Reference classes for the Destiny SDK."""

from pydantic import UUID4, BaseModel, Field

from .enhancements import Enhancement
from .identifiers import ExternalIdentifier
from .visibility import Visibility


class Reference(BaseModel):
    """Core reference class."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    id: UUID4 = Field(
        description="The ID of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        default=None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list[Enhancement] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )
