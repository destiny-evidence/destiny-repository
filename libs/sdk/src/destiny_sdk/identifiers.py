"""Identifier classes for the Destiny SDK."""

from enum import StrEnum, auto
from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, Field, field_validator


class ExternalIdentifierType(StrEnum):
    """
    The type of identifier used to identify a reference.

    This is used to identify the type of identifier used in the `ExternalIdentifier`
    class.
    **Allowed values**:
    - `doi`: A DOI (Digital Object Identifier) which is a unique identifier for a
    document.
    - `pmid`: A PubMed ID which is a unique identifier for a document in PubMed.
    - `openalex`: An OpenAlex ID which is a unique identifier for a document in
    OpenAlex.
    - `other`: Any other identifier not defined. This should be used sparingly.
    """

    DOI = auto()
    PM_ID = auto()
    OPEN_ALEX = auto()
    OTHER = auto()


def remove_doi_url(value: str) -> str:
    """Remove the URL part of the DOI if it exists."""
    return (
        value.removeprefix("http://doi.org/").removeprefix("https://doi.org/").strip()
    )


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


class LinkedExternalIdentifier(BaseModel):
    """An external identifier which identifies a reference."""

    identifier: ExternalIdentifier = Field(
        description="The identifier of the reference.",
        discriminator="identifier_type",
    )
    reference_id: UUID4 = Field(
        description="The ID of the reference this identifier identifies."
    )
