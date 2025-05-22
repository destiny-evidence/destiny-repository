"""Models associated with references."""

import uuid
from enum import StrEnum
from typing import Self

import destiny_sdk

# Explicitly import these models for easy use in the rest of the codebase
from destiny_sdk.enhancements import EnhancementContent, EnhancementType  # noqa: F401
from destiny_sdk.identifiers import ExternalIdentifier, ExternalIdentifierType
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
)

from app.core.exceptions import SDKToDomainError
from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.persistence.blob.models import BlobStorageFile

ExternalIdentifierAdapter: TypeAdapter[ExternalIdentifier] = TypeAdapter(
    ExternalIdentifier,
)


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


class BatchEnhancementRequestStatus(StrEnum):
    """
    The status of an enhancement request.

    **Allowed values**:
    - `received`: Enhancement request has been received by the robot.
    - `accepted`: Enhancement request has been accepted by the robot.
    - `rejected`: Enhancement request has been rejected by the robot.
    - `partial_failed`: Some enhancements failed to create.
    - `failed`: All enhancements failed to create.
    - `processed`: Enhancements have been received by the repo and are being validated.
    - `completed`: All enhancements have been created.
    """

    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    PROCESSED = "processed"
    COMPLETED = "completed"


class Visibility(StrEnum):
    """
    The visibility of a data element in the repository.

    This is used to manage whether information should be publicly available or
    restricted (generally due to copyright constraints from publishers).

    TODO: Implement data governance layer to manage this.

    **Allowed values**:

    - `public`: Visible to the general public without authentication.
    - `restricted`: Requires authentication to be visible.
    - `hidden`: Is not visible, but may be passed to data mining processes.
    """

    PUBLIC = "public"
    RESTRICTED = "restricted"
    HIDDEN = "hidden"


class Reference(DomainBaseModel, SQLAttributeMixin):
    """Core reference model with database attributes included."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
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

    def to_sdk(self) -> destiny_sdk.references.Reference:
        """Convert the reference to the SDK model."""
        try:
            return destiny_sdk.references.Reference(
                id=self.id,
                visibility=self.visibility,
                identifiers=[
                    identifier.to_sdk().identifier
                    for identifier in self.identifiers or []
                ],
                enhancements=[
                    enhancement.to_sdk() for enhancement in self.enhancements or []
                ],
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    @classmethod
    def from_file_input(
        cls,
        reference_in: destiny_sdk.references.ReferenceFileInput,
        reference_id: uuid.UUID | None = None,
    ) -> Self:
        """Create a reference including id hydration."""
        try:
            reference = cls(
                visibility=reference_in.visibility,
            )
            if reference_id:
                reference.id = reference_id
            reference.identifiers = [
                LinkedExternalIdentifier(
                    reference_id=reference.id, identifier=identifier
                )
                for identifier in reference_in.identifiers or []
            ]
            reference.enhancements = [
                Enhancement.model_validate(
                    enhancement.model_dump() | {"reference_id": reference.id}
                )
                for enhancement in reference_in.enhancements or []
            ]
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
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
        try:
            return cls.model_validate(
                external_identifier.model_dump(),
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def to_sdk(self) -> destiny_sdk.identifiers.LinkedExternalIdentifier:
        """Convert the external identifier to the SDK model."""
        try:
            return destiny_sdk.identifiers.LinkedExternalIdentifier(
                identifier=ExternalIdentifierAdapter.validate_python(self.identifier),
                reference_id=self.reference_id,
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception


class GenericExternalIdentifier(DomainBaseModel):
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
            identifier=str(external_identifier.identifier),
            identifier_type=external_identifier.identifier_type,
            other_identifier_name=external_identifier.other_identifier_name
            if hasattr(external_identifier, "other_identifier_name")
            else None,
        )


class ExternalIdentifierSearch(GenericExternalIdentifier):
    """Model to search for an external identifier."""


class ExternalIdentifierParseResult(BaseModel):
    """Result of an attempt to parse an external identifier."""

    external_identifier: ExternalIdentifier | None = Field(
        default=None,
        description="The external identifier to create",
        discriminator="identifier_type",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the parsing process",
    )


class Enhancement(DomainBaseModel, SQLAttributeMixin):
    """Core enhancement model with database attributes included."""

    source: str = Field(
        description="The enhancement source for tracking provenance.",
    )
    visibility: Visibility = Field(
        description="The level of visibility of the enhancement"
    )
    robot_version: str | None = Field(
        default=None,
        description="The version of the robot that generated the content.",
    )
    content_version: uuid.UUID = Field(
        description="""
        UUID regenerated when the content changes.
        Can be used to identify when content has changed.
        """,
        default_factory=uuid.uuid4,
    )
    content: EnhancementContent = Field(
        discriminator="enhancement_type",
        description="The content of the enhancement.",
    )
    reference_id: uuid.UUID = Field(
        description="The ID of the reference this enhancement is associated with."
    )

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )

    @classmethod
    def from_sdk(
        cls,
        enhancement: destiny_sdk.enhancements.Enhancement,
    ) -> Self:
        """Create an enhancement from the SDK model."""
        try:
            return cls.model_validate(
                enhancement.model_dump(),
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def to_sdk(self) -> destiny_sdk.enhancements.Enhancement:
        """Convert the enhancement to the SDK model."""
        try:
            return destiny_sdk.enhancements.Enhancement.model_validate(
                self.model_dump(),
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception


class EnhancementRequest(DomainBaseModel, SQLAttributeMixin):
    """Request to add an enhancement to a specific reference."""

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
    request_status: EnhancementRequestStatus = Field(
        default=EnhancementRequestStatus.RECEIVED,
        description="The status of the request to create an enhancement.",
    )
    error: str | None = Field(
        None,
        description="Error encountered during the enhancement process.",
    )

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )

    @classmethod
    def from_sdk(
        cls,
        enhancement_request: destiny_sdk.robots.EnhancementRequestIn,
    ) -> Self:
        """Create an enhancement request from the SDK model."""
        try:
            return cls.model_validate(
                enhancement_request.model_dump(),
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def to_sdk(self) -> destiny_sdk.robots.EnhancementRequestRead:
        """Convert the enhancement request to the SDK model."""
        try:
            return destiny_sdk.robots.EnhancementRequestRead.model_validate(
                self.model_dump(),
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception


class BatchEnhancementRequest(DomainBaseModel, SQLAttributeMixin):
    """Request to add enhancements to a list of references."""

    reference_ids: list[uuid.UUID] = Field(
        description="The IDs of the references these enhancements are associated with."
    )
    robot_id: uuid.UUID = Field(
        description="The robot to request the enhancement from."
    )
    request_status: BatchEnhancementRequestStatus = Field(
        default=BatchEnhancementRequestStatus.RECEIVED,
        description="The status of the request to create an enhancement.",
    )
    enhancement_parameters: dict | None = Field(
        default=None,
        description="Additional optional parameters to pass through to the robot.",
    )
    error: str | None = Field(
        default=None,
        description="""
Procedural error affecting all references encountered during the enhancement process.
Errors for individual references are provided <TBC>.
""",
    )
    reference_data_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing the reference data for the robot.",
    )

    @property
    def n_references(self) -> int:
        """The number of references in the request."""
        return len(self.reference_ids)

    @classmethod
    def from_sdk(
        cls,
        enhancement_request: destiny_sdk.robots.BatchEnhancementRequestIn,
    ) -> Self:
        """Create an enhancement request from the SDK model."""
        try:
            return cls.model_validate(enhancement_request.model_dump())
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def to_sdk(self) -> destiny_sdk.robots.BatchEnhancementRequestRead:
        """Convert the enhancement request to the SDK model."""
        try:
            return destiny_sdk.robots.BatchEnhancementRequestRead.model_validate(
                self.model_dump() | {"reference_data_url": self.reference_data_file},
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception


class EnhancementParseResult(BaseModel):
    """Result of an attempt to parse an enhancement."""

    enhancement: destiny_sdk.enhancements.EnhancementFileInput | None = Field(
        default=None,
        description="The enhancement to create",
    )
    error: str | None = Field(
        default=None,
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
        default=None,
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
