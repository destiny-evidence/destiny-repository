"""Identifier classes for the Destiny SDK."""

import uuid
from enum import StrEnum, auto
from typing import Annotated, Literal, Self

from pydantic import UUID4, BaseModel, Field, TypeAdapter, field_validator


class ExternalIdentifierType(StrEnum):
    """
    The type of identifier used to identify a reference.

    This is used to identify the type of identifier used in the `ExternalIdentifier`
    class.
    """

    DOI = auto()
    """A DOI (Digital Object Identifier) which is a unique identifier for a document."""
    PM_ID = auto()
    """A PubMed ID which is a unique identifier for a document in PubMed."""
    OPEN_ALEX = auto()
    """An OpenAlex ID which is a unique identifier for a document in OpenAlex."""
    OTHER = auto()
    """Any other identifier not defined. This should be used sparingly."""


class DOIIdentifier(BaseModel):
    """An external identifier representing a DOI."""

    identifier: str = Field(
        description="The DOI of the reference.",
        pattern=r"^10\.\d{4,9}/[-._;()/:a-zA-Z0-9%<>\[\]+&]+$",
    )
    identifier_type: Literal[ExternalIdentifierType.DOI] = Field(
        ExternalIdentifierType.DOI, description="The type of identifier used."
    )

    @field_validator("identifier", mode="before")
    @classmethod
    def remove_doi_url(cls, value: str) -> str:
        """Remove the URL part of the DOI if it exists."""
        return (
            value.removeprefix("http://doi.org/")
            .removeprefix("https://doi.org/")
            .strip()
        )


class PubMedIdentifier(BaseModel):
    """An external identifier representing a PubMed ID."""

    identifier: int = Field(description="The PubMed ID of the reference.")
    identifier_type: Literal[ExternalIdentifierType.PM_ID] = Field(
        ExternalIdentifierType.PM_ID, description="The type of identifier used."
    )


class OpenAlexIdentifier(BaseModel):
    """An external identifier representing an OpenAlex ID."""

    identifier: str = Field(
        description="The OpenAlex ID of the reference.", pattern=r"^W\d+$"
    )
    identifier_type: Literal[ExternalIdentifierType.OPEN_ALEX] = Field(
        ExternalIdentifierType.OPEN_ALEX, description="The type of identifier used."
    )

    @field_validator("identifier", mode="before")
    @classmethod
    def remove_open_alex_url(cls, value: str) -> str:
        """Remove the OpenAlex URL if it exists."""
        return (
            value.removeprefix("http://openalex.org/")
            .removeprefix("https://openalex.org/")
            .strip()
        )


class OtherIdentifier(BaseModel):
    """An external identifier not otherwise defined by the repository."""

    identifier: str = Field(description="The identifier of the reference.")
    identifier_type: Literal[ExternalIdentifierType.OTHER] = Field(
        ExternalIdentifierType.OTHER, description="The type of identifier used."
    )
    other_identifier_name: str = Field(
        description="The name of the undocumented identifier type."
    )


#: Union type for all external identifiers.
ExternalIdentifier = Annotated[
    DOIIdentifier | PubMedIdentifier | OpenAlexIdentifier | OtherIdentifier,
    Field(discriminator="identifier_type"),
]

ExternalIdentifierAdapter: TypeAdapter[ExternalIdentifier] = TypeAdapter(
    ExternalIdentifier
)


class LinkedExternalIdentifier(BaseModel):
    """An external identifier which identifies a reference."""

    identifier: ExternalIdentifier = Field(
        description="The identifier of the reference.",
        discriminator="identifier_type",
    )
    reference_id: UUID4 = Field(
        description="The ID of the reference this identifier identifies."
    )


class IdentifierLookup(BaseModel):
    """An external identifier lookup."""

    identifier: str = Field(description="The identifier value.")
    identifier_type: ExternalIdentifierType | None = Field(
        description="The type of identifier used. If not provided, it is assumed to"
        " be a DESTINY identifier.",
    )
    other_identifier_name: str | None = Field(
        default=None,
        description="The name of the undocumented identifier type.",
    )

    def serialize(self) -> str:
        """Serialize the identifier lookup to a string."""
        if self.identifier_type is None:
            return self.identifier
        if self.identifier_type == ExternalIdentifierType.OTHER:
            return f"other:{self.other_identifier_name}:{self.identifier}"
        return f"{self.identifier_type.value.lower()}:{self.identifier}"

    @classmethod
    def parse(cls, identifier_lookup_string: str, delimiter: str = ":") -> Self:
        """Parse an identifier string into an IdentifierLookup."""
        if delimiter not in identifier_lookup_string:
            try:
                UUID4(identifier_lookup_string)
            except ValueError as exc:
                msg = (
                    f"Invalid identifier lookup string: {identifier_lookup_string}. "
                    "Must be UUIDv4 if no identifier type is specified."
                )
                raise ValueError(msg) from exc
            return cls(
                identifier=identifier_lookup_string,
                identifier_type=None,
            )
        identifier_type, identifier = identifier_lookup_string.split(delimiter, 1)
        if identifier_type == ExternalIdentifierType.OTHER:
            if delimiter not in identifier:
                msg = (
                    f"Invalid identifier lookup string: {identifier_lookup_string}. "
                    "Other identifier type must include other identifier name."
                )
                raise ValueError(msg)
            other_identifier_type, identifier = identifier.split(delimiter, 1)
            return cls(
                identifier=identifier,
                identifier_type=ExternalIdentifierType.OTHER,
                other_identifier_name=other_identifier_type,
            )
        if identifier_type not in ExternalIdentifierType:
            msg = (
                f"Invalid identifier lookup string: {identifier_lookup_string}. "
                f"Unknown identifier type: {identifier_type}."
            )
            raise ValueError(msg)
        return cls(
            identifier=identifier,
            identifier_type=ExternalIdentifierType(identifier_type),
        )

    @classmethod
    def from_identifier(cls, identifier: ExternalIdentifier | UUID4) -> Self:
        """Create an IdentifierLookup from an ExternalIdentifier or UUID4."""
        if isinstance(identifier, uuid.UUID):
            return cls(identifier=str(identifier), identifier_type=None)
        return cls(
            identifier=str(identifier.identifier),
            identifier_type=identifier.identifier_type,
            other_identifier_name=getattr(identifier, "other_identifier_name", None),
        )

    def to_identifier(self) -> ExternalIdentifier | UUID4:
        """Convert into an ExternalIdentifier or UUID4 if it has no identifier_type."""
        if self.identifier_type is None:
            return UUID4(self.identifier)
        return ExternalIdentifierAdapter.validate_python(self.model_dump())
