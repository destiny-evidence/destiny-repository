"""Anti-corruption service for references domain."""

from uuid import UUID

import destiny_sdk
from pydantic import ValidationError

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.references.models.models import (
    AnnotationFilter,
    Enhancement,
    EnhancementRequest,
    ExternalIdentifierAdapter,
    IdentifierLookup,
    LinkedExternalIdentifier,
    PublicationYearRange,
    Reference,
    ReferenceDuplicateDecision,
    RobotAutomation,
    RobotEnhancementBatch,
    RobotResultValidationEntry,
)
from app.domain.service import GenericAntiCorruptionService
from app.persistence.blob.models import BlobSignedUrlType
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.persistence import ESSearchResult


class ReferenceAntiCorruptionService(GenericAntiCorruptionService):
    """Anti-corruption service for translating between Reference domain and SDK."""

    def __init__(self, blob_repository: BlobRepository) -> None:
        """Initialize the anti-corruption service."""
        self._blob_repository = blob_repository
        super().__init__()

    def reference_from_sdk_file_input(
        self,
        reference_in: destiny_sdk.references.ReferenceFileInput,
        reference_id: UUID | None = None,
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
        reference_id: UUID | None = None,
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

    async def robot_enhancement_batch_to_sdk(
        self,
        robot_enhancement_batch: "RobotEnhancementBatch",
    ) -> destiny_sdk.robots.RobotEnhancementBatchRead:
        """Convert the robot enhancement batch to the SDK model."""
        try:
            return destiny_sdk.robots.RobotEnhancementBatchRead.model_validate(
                robot_enhancement_batch.model_dump()
                | {
                    "reference_data_url": await self._blob_repository.get_signed_url(
                        robot_enhancement_batch.reference_data_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if robot_enhancement_batch.reference_data_file
                    else None,
                    "result_storage_url": await self._blob_repository.get_signed_url(
                        robot_enhancement_batch.result_file, BlobSignedUrlType.UPLOAD
                    )
                    if robot_enhancement_batch.result_file
                    else None,
                    "validation_result_url": await self._blob_repository.get_signed_url(
                        robot_enhancement_batch.validation_result_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if robot_enhancement_batch.validation_result_file
                    else None,
                },
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    async def robot_enhancement_batch_to_sdk_robot(
        self,
        robot_enhancement_batch: "RobotEnhancementBatch",
    ) -> destiny_sdk.robots.RobotEnhancementBatch:
        """Convert robot enhancement batch to the new SDK RobotEnhancementBatch."""
        try:
            return destiny_sdk.robots.RobotEnhancementBatch(
                id=robot_enhancement_batch.id,
                reference_storage_url=await self._blob_repository.get_signed_url(
                    robot_enhancement_batch.reference_data_file,
                    BlobSignedUrlType.DOWNLOAD,
                )
                if robot_enhancement_batch.reference_data_file
                else None,
                result_storage_url=await self._blob_repository.get_signed_url(
                    robot_enhancement_batch.result_file, BlobSignedUrlType.UPLOAD
                )
                if robot_enhancement_batch.result_file
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
        automation_id: UUID | None = None,
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

    def identifier_lookups_from_sdk(
        self,
        identifier_lookups_in: list[destiny_sdk.identifiers.IdentifierLookup],
    ) -> list[IdentifierLookup]:
        """Create a list of LinkedExternalIdentifier from the SDK model."""
        try:
            return [
                IdentifierLookup.model_validate(identifier_lookup.model_dump())
                for identifier_lookup in identifier_lookups_in
            ]
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def two_stage_reference_search_result_to_sdk(
        self,
        search_result: ESSearchResult,
        references: list[Reference],
    ) -> destiny_sdk.references.ReferenceSearchResult:
        """Convert a search result and retrieved references to the SDK model."""
        try:
            hit_order = {hit.id: i for i, hit in enumerate(search_result.hits)}
            return destiny_sdk.references.ReferenceSearchResult(
                total={
                    "count": search_result.total.value,
                    "is_lower_bound": search_result.total.relation == "gte",
                },
                page={
                    "count": len(search_result.hits),
                    "number": search_result.page,
                },
                references=[
                    self.reference_to_sdk(reference)
                    # Sort references according to search order
                    for reference in sorted(references, key=lambda r: hit_order[r.id])
                ],
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def publication_year_range_from_query_parameter(
        self,
        start_year: int | None,
        end_year: int | None,
    ) -> PublicationYearRange:
        """Parse a publication year range from a query parameter."""
        return PublicationYearRange(start=start_year, end=end_year)

    def annotation_filter_from_query_parameter(
        self,
        annotation_filter_string: str,
    ) -> AnnotationFilter:
        """Parse an annotation filter from a query parameter."""
        if "@" in annotation_filter_string:
            score = float(annotation_filter_string.split("@")[-1])
            annotation_filter_string = annotation_filter_string.rsplit("@", 1)[0]
        else:
            score = None

        if "/" not in annotation_filter_string:
            scheme, label = annotation_filter_string, None
        else:
            scheme, label = annotation_filter_string.split("/", 1)

        return AnnotationFilter(
            scheme=scheme,
            label=label,
            score=score,
        )

    def duplicate_decision_from_sdk_make(
        self,
        make_duplicate_decision: destiny_sdk.deduplication.MakeDuplicateDecision,
    ) -> ReferenceDuplicateDecision:
        """Convert a MakeDuplicateDecision SDK model to a ReferenceDuplicateDecision."""
        try:
            reference_duplicate_decision = ReferenceDuplicateDecision(
                reference_id=make_duplicate_decision.reference_id,
                duplicate_determination=make_duplicate_decision.duplicate_determination,
                canonical_reference_id=make_duplicate_decision.canonical_reference_id,
                detail=make_duplicate_decision.detail,
            )
            reference_duplicate_decision.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        return reference_duplicate_decision

    def duplicate_decision_to_sdk_make_result(
        self,
        decision: ReferenceDuplicateDecision,
    ) -> destiny_sdk.deduplication.MakeDuplicateDecisionResult:
        """Convert a ReferenceDuplicateDecision to a MakeDuplicateDecisionResult."""
        return destiny_sdk.deduplication.MakeDuplicateDecisionResult(
            id=decision.id,
            reference_id=decision.reference_id,
            outcome=decision.duplicate_determination,
            canonical_reference_id=decision.canonical_reference_id,
            active_decision=decision.active_decision,
            detail=decision.detail,
        )
