"""Reference classes for the Destiny SDK."""

from typing import Self

from pydantic import UUID4, BaseModel, Field

from .enhancements import Enhancement, EnhancementFileInput
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

    def to_jsonl(self) -> str:
        """Convert the model to a JSONL string."""
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_jsonl(cls, jsonl: str) -> Self:
        """Create a Reference object from a JSONL string."""
        return cls.model_validate_json(jsonl)


class ReferenceFileInput(BaseModel):
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

    def to_jsonl(self) -> str:
        """Convert the model to a JSONL string."""
        return self.model_dump_json(exclude_none=True)
