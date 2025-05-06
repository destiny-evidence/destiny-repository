"""Models associated with references."""

import uuid
from enum import StrEnum
from typing import Self

import destiny_sdk
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
)

from app.domain.base import DomainBaseModel, SQLAttributeMixin

"""Alias the SDK models for easy use and to allow for easier refactoring."""
EnhancementType = destiny_sdk.enhancements.EnhancementType
ExternalIdentifierType = destiny_sdk.identifiers.ExternalIdentifierType
ExternalIdentifier = destiny_sdk.identifiers.ExternalIdentifier
Visibility = destiny_sdk.visibility.Visibility


class EnhancementRequestStatus(StrEnum):
    """
    The status of an enhancement request.

    **Allowed values**:
    - `received`: Enhancement request has been received.
    - `accepted`: Enhancement request has been accepted.
    - `rejected`: Enhancement request has been rejected.
    - `failed`: Enhancement failed to create.
    - `completed`: Enhancement has been created.
    """

    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    COMPLETED = "completed"


class ReferenceIn(DomainBaseModel):
    """Input for creating a reference."""

    visibility: Visibility = Field(
        Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list["Enhancement"] | None = Field(
        None,
        description="A list of enhancements for the reference",
    )


class Reference(DomainBaseModel, SQLAttributeMixin):
    """Core reference model with database attributes included."""

    visibility: Visibility = Field(
        Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list["LinkedExternalIdentifier"] | None = Field(
        default=None,
        description="A list of `LinkedExternalIdentifiers` for the Reference",
    )
    enhancements: list["Enhancement"] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )

    @classmethod
    def from_sdk(
        cls,
        reference: destiny_sdk.references.Reference,
    ) -> Self:
        """Create a reference from the SDK model."""
        return cls(
            **reference.model_dump(),
        )

    def to_sdk(self) -> destiny_sdk.references.Reference:
        """Convert the reference to the SDK model."""
        return destiny_sdk.references.Reference(
            **self.model_dump(),
            identifiers=[
                identifier.to_sdk().identifier for identifier in self.identifiers or []
            ],
            enhancements=[
                enhancement.to_sdk() for enhancement in self.enhancements or []
            ],
        )

    @classmethod
    def from_file_input(
        cls,
        reference_in: ReferenceIn,
        reference_id: uuid.UUID | None = None,
    ) -> Self:
        """Create a reference including id hydration."""
        reference = cls(
            visibility=reference_in.visibility,
        )
        if reference_id:
            reference.id = reference_id
        reference.identifiers = [
            LinkedExternalIdentifier(reference_id=reference.id, identifier=identifier)
            for identifier in reference_in.identifiers or []
        ]
        reference.enhancements = [
            Enhancement(**enhancement.model_dump(), reference_id=reference.id)
            for enhancement in reference_in.enhancements or []
        ]
        return reference


class LinkedExternalIdentifier(DomainBaseModel, SQLAttributeMixin):
    """External identifier model with database attributes included."""

    identifier: destiny_sdk.identifiers.ExternalIdentifier = Field(
        description="The identifier itself.", discriminator="identifier_type"
    )
    reference_id: uuid.UUID = Field(
        description="The ID of the reference this identifier identifies."
    )
    reference: Reference | None = Field(
        default=None,
        description="The reference this identifier identifies.",
    )

    @classmethod
    def from_sdk(
        cls,
        external_identifier: destiny_sdk.identifiers.LinkedExternalIdentifier,
    ) -> Self:
        """Create an external identifier from the SDK model."""
        return cls(
            **external_identifier.model_dump(),
        )

    def to_sdk(self) -> destiny_sdk.identifiers.LinkedExternalIdentifier:
        """Convert the external identifier to the SDK model."""
        return TypeAdapter(
            destiny_sdk.identifiers.LinkedExternalIdentifier,
        ).validate_python(self.model_dump())


class GenericExternalIdentifier(BaseModel):
    """
    Generic external identifier model for all subtypes.

    The identifier is casted to a string for all inheriters.
    """

    identifier: str = Field(
        description="The identifier itself.",
    )
    identifier_type: ExternalIdentifierType = Field(
        description="The type of the identifier.",
    )
    other_identifier_name: str | None = Field(
        None,
        description="The name of the other identifier.",
    )

    @classmethod
    def from_specific(
        cls,
        external_identifier: ExternalIdentifier,
    ) -> Self:
        """Create a generic external identifier from a specific implementation."""
        return cls(
            **external_identifier.model_dump(),
        )


class ExternalIdentifierSearch(GenericExternalIdentifier):
    """Model to search for an external identifier."""


class ExternalIdentifierParseResult(BaseModel):
    """Result of an attempt to parse an external identifier."""

    external_identifier: ExternalIdentifier | None = Field(
        None,
        description="The external identifier to create",
        discriminator="identifier_type",
    )
    error: str | None = Field(
        None,
        description="Error encountered during the parsing process",
    )


class EnhancementBase(DomainBaseModel):
    """
    Base enhancement class.

    An enhancement is any data about a reference which is in addition to the
    identifiers of that reference. Anything which is useful is generally an
    enhancement. They will be flattened and composed for search and access.
    """

    source: str = Field(
        description="The enhancement source for tracking provenance.",
    )
    visibility: Visibility = Field(
        description="The level of visibility of the enhancement"
    )
    enhancement_type: EnhancementType = Field(description="The type of enhancement.")
    processor_version: str | None = Field(
        None,
        description="The version of the processor that generated the content.",
    )
    content_version: uuid.UUID = Field(
        description="""
        UUID regenerated when the content changes.
        Can be used to identify when content has changed.
        """,
        default_factory=uuid.uuid4,
    )
    content: destiny_sdk.enhancements.EnhancementContent = Field(
        discriminator="enhancement_type",
        description="The content of the enhancement.",
    )


class EnhancementIn(EnhancementBase):
    """Enhancement model used to ingest into the repository."""

    @classmethod
    def from_sdk(
        cls,
        enhancement: destiny_sdk.enhancements.EnhancementIn,
    ) -> Self:
        """Create an enhancement from the SDK model."""
        return cls(
            **enhancement.model_dump(),
        )


class EnhancementFileInput(EnhancementBase):
    """Enhancement model used to parse from a file input."""


class Enhancement(EnhancementBase, SQLAttributeMixin):
    """Core enhancement model with database attributes included."""

    reference_id: uuid.UUID = Field(
        description="The ID of the reference this enhancement is associated with."
    )

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )

    def to_sdk(self) -> destiny_sdk.enhancements.Enhancement:
        """Convert the enhancement to the SDK model."""
        return destiny_sdk.enhancements.Enhancement(
            **self.model_dump(),
        )


class EnhancementRequestBase(DomainBaseModel):
    """Base enhancement request class."""

    reference_id: uuid.UUID = Field(
        description="The ID of the reference this enhancement is associated with."
    )

    robot_id: uuid.UUID = Field(
        description="The robot to request the enhancement from."
    )

    enhancement_parameters: dict | None = Field(
        default=None,
        description="Additional optional parameters to pass through to the robot.",
    )


class EnhancementRequestIn(EnhancementRequestBase):
    """The model for requesting an enhancement on specific reference."""

    @classmethod
    def from_sdk(
        cls,
        enhancement_request: destiny_sdk.robots.EnhancementRequestIn,
    ) -> Self:
        """Create an enhancement request from the SDK model."""
        return cls(
            **enhancement_request.model_dump(),
        )


class EnhancementRequest(EnhancementRequestBase, SQLAttributeMixin):
    """Request to add an enhancement to a specific reference."""

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )

    request_status: EnhancementRequestStatus = Field(
        default=EnhancementRequestStatus.RECEIVED,
        description="The status of the request to create an enhancement.",
    )

    error: str | None = Field(
        None,
        description="Error encountered during the enhancement process.",
    )

    def to_sdk(self) -> destiny_sdk.robots.EnhancementRequest:
        """Convert the enhancement request to the SDK model."""
        return destiny_sdk.robots.EnhancementRequest(
            **self.model_dump(),
        )


class EnhancementParseResult(BaseModel):
    """Result of an attempt to parse an enhancement."""

    enhancement: destiny_sdk.enhancements.EnhancementIn | None = Field(
        None,
        description="The enhancement to create",
    )
    error: str | None = Field(
        None,
        description="Error encountered during the parsing process",
    )


class ReferenceCreateResult(BaseModel):
    """
    Result of an attempt to create a reference.

    If reference is None, no reference was created and errors will be populated.
    If reference exists and there are errors, the reference was created but there
    were errors in the hydration.
    If reference exists and there are no errors, the reference was created and all
    enhancements/identifiers were hydrated successfully from the input.
    """

    reference: Reference | None = Field(
        None,
        description="""
    The created reference.
    If None, no reference was created.
    """,
    )
    errors: list[str] = Field(
        default_factory=list,
        description="A list of errors encountered during the creation process",
    )

    @property
    def error_str(self) -> str | None:
        """Return a string of errors if they exist."""
        return "\n\n".join(e.strip() for e in self.errors) if self.errors else None
