"""Anti-corruption service for references domain."""

import uuid

import destiny_sdk
from pydantic import ValidationError

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchRobotResultValidationEntry,
    Enhancement,
    EnhancementRequest,
    LinkedExternalIdentifier,
    Reference,
    RobotAutomation,
)
from app.domain.service import AntiCorruptionService
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import BlobSignedUrlType


class ReferenceAntiCorruptionService(AntiCorruptionService):
    """Anti-corruption service for translating between Reference domain and SDK."""

    def __init__(self, blob_client: GenericBlobStorageClient) -> None:
        """Initialize the anti-corruption service."""
        self._blob_client = blob_client
        super().__init__()

    def reference_from_file_input(
        self,
        data: destiny_sdk.references.ReferenceFileInput,
        reference_id: uuid.UUID | None = None,
    ) -> Reference:
        """Create a reference from a file input including id hydration."""
        try:
            reference = Reference(
                visibility=data.visibility,
            )
            if reference_id:
                reference.id = reference_id
            reference.identifiers = [
                LinkedExternalIdentifier(
                    reference_id=reference.id, identifier=identifier
                )
                for identifier in data.identifiers or []
            ]
            reference.enhancements = [
                Enhancement.model_validate(
                    enhancement.model_dump() | {"reference_id": reference.id}
                )
                for enhancement in data.enhancements or []
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
            return destiny_sdk.references.Reference.model_validate(
                reference.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def external_identifier_to_sdk(
        self, identifier: LinkedExternalIdentifier
    ) -> destiny_sdk.identifiers.LinkedExternalIdentifier:
        """Convert the external identifier to a LinkedExternalIdentifier SDK model."""
        try:
            return destiny_sdk.identifiers.LinkedExternalIdentifier.model_validate(
                identifier.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def external_identifier_from_sdk(
        self, data: destiny_sdk.identifiers.LinkedExternalIdentifier
    ) -> LinkedExternalIdentifier:
        """Create a LinkedExternalIdentifier from the SDK model."""
        try:
            identifier = LinkedExternalIdentifier.model_validate(data.model_dump())
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
        data: destiny_sdk.references.Enhancement,
        reference_id: uuid.UUID | None = None,
    ) -> Enhancement:
        """Create an Enhancement from the SDK model with optional ID grafting."""
        try:
            enhancement_model = data.model_dump()

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

    def enhancement_request_to_sdk(
        self, enhancement_request: EnhancementRequest
    ) -> destiny_sdk.robots.EnhancementRequestRead:
        """Convert the enhancement request to a BatchEnhancementRequest SDK model."""
        try:
            return destiny_sdk.robots.EnhancementRequestRead.model_validate(
                enhancement_request.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def enhancement_request_from_sdk(
        self,
        data: destiny_sdk.robots.EnhancementRequestIn,
    ) -> EnhancementRequest:
        """Create a BatchEnhancementRequest from the SDK model."""
        try:
            enhancement_request = EnhancementRequest.model_validate(data.model_dump())
            enhancement_request.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return enhancement_request

    def batch_enhancement_request_from_sdk(
        self,
        data: destiny_sdk.robots.BatchEnhancementRequestIn,
    ) -> BatchEnhancementRequest:
        """Create a BatchEnhancementRequest from the SDK model."""
        try:
            enhancement_request = BatchEnhancementRequest.model_validate(
                data.model_dump()
            )
            enhancement_request.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return enhancement_request

    async def batch_enhancement_request_to_sdk(
        self,
        enhancement_request: BatchEnhancementRequest,
    ) -> destiny_sdk.robots.BatchEnhancementRequestRead:
        """Convert the batch enhancement request to the SDK model."""
        try:
            return destiny_sdk.robots.BatchEnhancementRequestRead.model_validate(
                enhancement_request.model_dump()
                | {
                    "reference_data_url": await self._blob_client.generate_signed_url(
                        enhancement_request.reference_data_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if enhancement_request.reference_data_file
                    else None,
                    "result_storage_url": await self._blob_client.generate_signed_url(
                        enhancement_request.result_file, BlobSignedUrlType.UPLOAD
                    )
                    if enhancement_request.result_file
                    else None,
                    "validation_result_url": await self._blob_client.generate_signed_url(
                        enhancement_request.validation_result_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if enhancement_request.validation_result_file
                    else None,
                },
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    async def batch_robot_request_to_sdk(
        self,
        enhancement_request: BatchEnhancementRequest,
    ) -> destiny_sdk.robots.BatchRobotRequest:
        """Convert the batch robot request to the SDK model."""
        try:
            return destiny_sdk.robots.BatchRobotRequest(
                id=enhancement_request.id,
                reference_storage_url=await self._blob_client.generate_signed_url(
                    enhancement_request.reference_data_file, BlobSignedUrlType.DOWNLOAD
                )
                if enhancement_request.reference_data_file
                else None,
                result_storage_url=await self._blob_client.generate_signed_url(
                    enhancement_request.result_file, BlobSignedUrlType.UPLOAD
                )
                if enhancement_request.result_file
                else None,
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def batch_robot_result_validation_entry_to_sdk(
        self, entry: BatchRobotResultValidationEntry
    ) -> destiny_sdk.robots.BatchRobotResultValidationEntry:
        """Convert the batch robot result validation entry to the SDK model."""
        try:
            return destiny_sdk.robots.BatchRobotResultValidationEntry.model_validate(
                entry.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def robot_automation_from_sdk(
        self,
        data: destiny_sdk.robots.RobotAutomationIn,
    ) -> RobotAutomation:
        """Create a RobotAutomation from the SDK model."""
        try:
            robot_automation = RobotAutomation.model_validate(data.model_dump())
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
