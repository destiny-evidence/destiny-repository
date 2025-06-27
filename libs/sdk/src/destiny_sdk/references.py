"""Reference classes for the Destiny SDK."""

from typing import Self

from pydantic import UUID4, BaseModel, Field, TypeAdapter

from destiny_sdk.core import _JsonlFileInputMixIn
from destiny_sdk.enhancements import Enhancement, EnhancementFileInput
from destiny_sdk.identifiers import ExternalIdentifier
from destiny_sdk.visibility import Visibility

external_identifier_adapter = TypeAdapter(ExternalIdentifier)


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

    @classmethod
    def from_es(cls, es_reference: dict) -> Self:
        """Create a Reference from an Elasticsearch document."""
        return cls(
            id=es_reference["_id"],
            visibility=Visibility(es_reference["_source"]["visibility"]),
            identifiers=[
                external_identifier_adapter.validate_python(identifier)
                for identifier in es_reference["_source"].get("identifiers", [])
            ],
            enhancements=[
                Enhancement.model_validate(
                    enhancement | {"reference_id": es_reference["_id"]},
                )
                for enhancement in es_reference["_source"].get("enhancements", [])
            ],
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
