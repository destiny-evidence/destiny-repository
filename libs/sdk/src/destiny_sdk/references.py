"""Reference classes for the Destiny SDK."""

from pydantic import UUID4, BaseModel, Field

from destiny_sdk.core import _JsonlFileInputMixIn
from destiny_sdk.enhancements import Enhancement, EnhancementFileInput
from destiny_sdk.identifiers import ExternalIdentifier
from destiny_sdk.visibility import Visibility


class Reference(_JsonlFileInputMixIn, BaseModel):
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


class ReferenceFileInput(_JsonlFileInputMixIn, BaseModel):
    """Enhancement model used to marshall a file input."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        default=None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list[EnhancementFileInput] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )
