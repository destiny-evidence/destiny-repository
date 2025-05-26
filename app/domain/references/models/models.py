"""Models associated with references."""

import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Self

import destiny_sdk

# Explicitly import these models for easy use in the rest of the codebase
from destiny_sdk.enhancements import EnhancementContent, EnhancementType  # noqa: F401
from destiny_sdk.identifiers import ExternalIdentifier, ExternalIdentifierType
from pydantic import (
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
)

from app.core.exceptions import SDKToDomainError
from app.core.logger import get_logger
from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.domain.imports.models.models import CollisionStrategy
from app.persistence.blob.models import BlobSignedUrlType, BlobStorageFile

logger = get_logger()

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
    - `received`: Enhancement request has been received by the repo.
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

    def merge(
        self,
        incoming_reference: Self,
        collision_strategy: CollisionStrategy,
    ) -> None:
        """
        Merge an incoming reference into this one.

        Args:
            - existing_reference (Reference): The existing reference.
            - incoming_reference (Reference): The incoming reference.
            - collision_strategy (CollisionStrategy): The strategy to use for
                handling collisions.

        Returns:
            - Reference: The final reference to be persisted.

        """

        def _get_identifier_key(
            identifier: ExternalIdentifier,
        ) -> tuple[str, str | None]:
            """
            Get the key for an identifier.

            Args:
                - identifier (LinkedExternalIdentifier)

            Returns:
                - tuple[str, str | None]: The key for the identifier.

            """
            return (
                identifier.identifier_type,
                identifier.other_identifier_name
                if hasattr(identifier, "other_identifier_name")
                else None,
            )

        # Graft matching IDs from self to incoming
        for identifier in incoming_reference.identifiers or []:
            for existing_identifier in self.identifiers or []:
                if _get_identifier_key(identifier.identifier) == _get_identifier_key(
                    existing_identifier.identifier
                ):
                    identifier.id = existing_identifier.id
        for enhancement in incoming_reference.enhancements or []:
            for existing_enhancement in self.enhancements or []:
                if (enhancement.content.enhancement_type, enhancement.source) == (
                    existing_enhancement.content.enhancement_type,
                    existing_enhancement.source,
                ):
                    enhancement.id = existing_enhancement.id

        if not self.identifiers or not incoming_reference.identifiers:
            msg = "No identifiers found in merge. This should not happen."
            raise RuntimeError(msg)

        self.enhancements = self.enhancements or []
        incoming_reference.enhancements = incoming_reference.enhancements or []

        # Merge identifiers
        self.identifiers.extend(
            [
                identifier
                for identifier in incoming_reference.identifiers
                if _get_identifier_key(identifier.identifier)
                not in {
                    _get_identifier_key(identifier.identifier)
                    for identifier in self.identifiers
                }
            ]
        )

        # On an overwrite, we don't preserve the existing enhancements, only identifiers
        if collision_strategy == CollisionStrategy.OVERWRITE:
            self.enhancements = incoming_reference.enhancements.copy()
            return

        # Otherwise, merge enhancements
        self.enhancements.extend(
            [
                enhancement
                for enhancement in incoming_reference.enhancements
                if (enhancement.content.enhancement_type, enhancement.source)
                not in {
                    (enhancement.content.enhancement_type, enhancement.source)
                    for enhancement in self.enhancements
                }
            ]
        )

        return


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
        reference_id: uuid.UUID | None = None,
    ) -> Self:
        """Create an enhancement from the SDK model."""
        try:
            return cls.model_validate(
                enhancement.model_dump()
                | ({"reference_id": reference_id} if reference_id else {})
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
    result_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing the result data from the robot.",
    )
    validation_result_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing the validation result data from the robot.",
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

    def to_sdk(
        self,
        to_signed_url: Callable[
            [BlobStorageFile | None, BlobSignedUrlType], HttpUrl | None
        ],
    ) -> destiny_sdk.robots.BatchEnhancementRequestRead:
        """Convert the enhancement request to the SDK model."""
        try:
            return destiny_sdk.robots.BatchEnhancementRequestRead.model_validate(
                self.model_dump()
                | {
                    "reference_data_url": to_signed_url(
                        self.reference_data_file, BlobSignedUrlType.DOWNLOAD
                    ),
                    "result_storage_url": to_signed_url(
                        self.result_file, BlobSignedUrlType.UPLOAD
                    ),
                    "validation_result_url": to_signed_url(
                        self.validation_result_file, BlobSignedUrlType.DOWNLOAD
                    ),
                },
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def to_batch_robot_request_sdk(
        self,
        to_signed_url: Callable[
            [BlobStorageFile | None, BlobSignedUrlType], HttpUrl | None
        ],
    ) -> destiny_sdk.robots.BatchRobotRequest:
        """Convert the enhancement request to the SDK robot request model."""
        try:
            return destiny_sdk.robots.BatchRobotRequest(
                id=self.id,
                reference_storage_url=to_signed_url(
                    self.reference_data_file, BlobSignedUrlType.DOWNLOAD
                ),
                result_storage_url=to_signed_url(
                    self.result_file, BlobSignedUrlType.UPLOAD
                ),
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
