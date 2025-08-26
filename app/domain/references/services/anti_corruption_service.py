"""Anti-corruption service for references domain."""

import uuid

import destiny_sdk
from pydantic import ValidationError

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    ExternalIdentifierAdapter,
    LinkedExternalIdentifier,
    Reference,
    RobotAutomation,
    RobotResultValidationEntry,
)
from app.domain.service import GenericAntiCorruptionService
from app.persistence.blob.models import BlobSignedUrlType
from app.persistence.blob.repository import BlobRepository


class ReferenceAntiCorruptionService(GenericAntiCorruptionService):
    """Anti-corruption service for translating between Reference domain and SDK."""

    def __init__(self, blob_repository: BlobRepository) -> None:
        """Initialize the anti-corruption service."""
        self._blob_repository = blob_repository
        super().__init__()

    def reference_from_sdk_file_input(
        self,
        reference_in: destiny_sdk.references.ReferenceFileInput,
        reference_id: uuid.UUID | None = None,
    ) -> Reference:
        """Create a reference from a file input including id hydration."""
        try:
            reference = Reference(
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
            reference.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return reference

    def reference_to_sdk(
        self, reference: Reference
    ) -> destiny_sdk.references.Reference:
        """Convert the reference to a Reference SDK model."""
        try:
            return destiny_sdk.references.Reference(
                id=reference.id,
                visibility=reference.visibility,
                identifiers=[
                    self.external_identifier_to_sdk(identifier).identifier
                    for identifier in reference.identifiers or []
                ],
                enhancements=[
                    self.enhancement_to_sdk(enhancement)
                    for enhancement in reference.enhancements or []
                ],
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def external_identifier_to_sdk(
        self, identifier: LinkedExternalIdentifier
    ) -> destiny_sdk.identifiers.LinkedExternalIdentifier:
        """Convert the external identifier to a LinkedExternalIdentifier SDK model."""
        try:
            return destiny_sdk.identifiers.LinkedExternalIdentifier(
                identifier=ExternalIdentifierAdapter.validate_python(
                    identifier.identifier
                ),
                reference_id=identifier.reference_id,
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def external_identifier_from_sdk(
        self, identifier_in: destiny_sdk.identifiers.LinkedExternalIdentifier
    ) -> LinkedExternalIdentifier:
        """Create a LinkedExternalIdentifier from the SDK model."""
        try:
            identifier = LinkedExternalIdentifier.model_validate(
                identifier_in.model_dump()
            )
            identifier.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return identifier

    def enhancement_to_sdk(
        self, enhancement: Enhancement
    ) -> destiny_sdk.references.Enhancement:
        """Convert the enhancement to an Enhancement SDK model."""
        try:
            return destiny_sdk.references.Enhancement.model_validate(
                enhancement.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def enhancement_from_sdk(
        self,
        enhancement_in: destiny_sdk.references.Enhancement,
        reference_id: uuid.UUID | None = None,
    ) -> Enhancement:
        """Create an Enhancement from the SDK model with optional ID grafting."""
        try:
            enhancement_model = enhancement_in.model_dump()

            ## The SDK isn't allowed to pass in ids, so ignore this.
            enhancement_model.pop("id", None)

            enhancement = Enhancement.model_validate(
                enhancement_model
                | ({"reference_id": reference_id} if reference_id else {})
            )
            enhancement.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return enhancement

    def enhancement_request_from_sdk(
        self,
        enhancement_request_in: destiny_sdk.robots.EnhancementRequestIn,
    ) -> EnhancementRequest:
        """Create a EnhancementRequest from the SDK model."""
        try:
            enhancement_request = EnhancementRequest.model_validate(
                enhancement_request_in.model_dump()
            )
            enhancement_request.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return enhancement_request

    async def enhancement_request_to_sdk(
        self,
        enhancement_request: EnhancementRequest,
    ) -> destiny_sdk.robots.EnhancementRequestRead:
        """Convert the enhancement request to the SDK model."""
        try:
            return destiny_sdk.robots.EnhancementRequestRead.model_validate(
                enhancement_request.model_dump()
                | {
                    "reference_data_url": await self._blob_repository.get_signed_url(
                        enhancement_request.reference_data_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if enhancement_request.reference_data_file
                    else None,
                    "result_storage_url": await self._blob_repository.get_signed_url(
                        enhancement_request.result_file, BlobSignedUrlType.UPLOAD
                    )
                    if enhancement_request.result_file
                    else None,
                    "validation_result_url": await self._blob_repository.get_signed_url(
                        enhancement_request.validation_result_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if enhancement_request.validation_result_file
                    else None,
                },
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    async def enhancement_request_to_sdk_robot(
        self,
        enhancement_request: EnhancementRequest,
    ) -> destiny_sdk.robots.RobotRequest:
        """Convert the robot request to the SDK model."""
        try:
            return destiny_sdk.robots.RobotRequest(
                id=enhancement_request.id,
                reference_storage_url=await self._blob_repository.get_signed_url(
                    enhancement_request.reference_data_file, BlobSignedUrlType.DOWNLOAD
                )
                if enhancement_request.reference_data_file
                else None,
                result_storage_url=await self._blob_repository.get_signed_url(
                    enhancement_request.result_file, BlobSignedUrlType.UPLOAD
                )
                if enhancement_request.result_file
                else None,
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def robot_result_validation_entry_to_sdk(
        self, entry: RobotResultValidationEntry
    ) -> destiny_sdk.robots.RobotResultValidationEntry:
        """Convert the robot result validation entry to the SDK model."""
        try:
            return destiny_sdk.robots.RobotResultValidationEntry.model_validate(
                entry.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def robot_automation_from_sdk(
        self,
        robot_automation_in: destiny_sdk.robots.RobotAutomationIn,
        automation_id: uuid.UUID | None = None,
    ) -> RobotAutomation:
        """Create a RobotAutomation from the SDK model."""
        try:
            robot_automation = RobotAutomation.model_validate(
                robot_automation_in.model_dump()
            )
            if automation_id:
                robot_automation.id = automation_id
            robot_automation.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return robot_automation

    def robot_automation_to_sdk(
        self, robot_automation: RobotAutomation
    ) -> destiny_sdk.robots.RobotAutomation:
        """Convert the robot automation to a RobotAutomation SDK model."""
        try:
            return destiny_sdk.robots.RobotAutomation.model_validate(
                robot_automation.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception
