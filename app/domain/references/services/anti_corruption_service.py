"""Anti-corruption service for references domain."""

from collections.abc import Sequence
from uuid import UUID

import destiny_sdk
from pydantic import ValidationError

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.references.models.models import (
    AnnotationFilter,
    CrossFacetCell,
    Enhancement,
    EnhancementRequest,
    EnhancementType,
    ExternalIdentifierAdapter,
    FacetType,
    FullTextEnhancement,
    IdentifierLookup,
    LinkedDataConceptFilter,
    LinkedDataCountryFilter,
    LinkedDataCountryWBRegionFilter,
    LinkedExternalIdentifier,
    PublicationYearRange,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceExport,
    RobotAutomation,
    RobotEnhancementBatch,
    RobotResultValidationEntry,
    SearchExport,
)
from app.domain.references.services.access_control_service import RedactedReference
from app.domain.service import GenericAntiCorruptionService
from app.persistence.blob.models import BlobSignedUrlType, BlobStorageFile
from app.persistence.blob.repository import URLSigner
from app.persistence.es.persistence import (
    ESFacetBucket,
    ESSearchResult,
    ESSearchTotal,
)
from app.utils.strings import demojibake, demojibake_walk

# JSON-LD literal keys carrying human-readable free text
_LINKED_DATA_TEXT_KEYS = frozenset({"name", "description", "supportingText", "@value"})


class ReferenceAntiCorruptionService(GenericAntiCorruptionService):
    """Anti-corruption service for translating between Reference domain and SDK."""

    def __init__(self, sign_url: URLSigner) -> None:
        """
        Initialize the anti-corruption service.

        :param sign_url: Callable that signs a blob storage file into a URL.
            Typically ``BlobRepository.get_signed_url``.
        """
        self._sign_url = sign_url
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
                self.enhancement_from_sdk(enhancement, reference_id=reference.id)
                for enhancement in reference_in.enhancements or []
            ]
            reference.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return reference

    async def reference_to_sdk(
        self, reference: RedactedReference
    ) -> destiny_sdk.references.Reference:
        """Convert the reference to a Reference SDK model."""
        try:
            enhancements = [
                await self.enhancement_to_sdk(enhancement)
                for enhancement in reference.enhancements or []
            ]
            return destiny_sdk.references.Reference(
                id=reference.id,
                visibility=reference.visibility,
                identifiers=[
                    self.external_identifier_to_sdk(identifier).identifier
                    for identifier in reference.identifiers or []
                ],
                enhancements=enhancements,
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

    async def full_text_enhancement_content_to_sdk(
        self,
        full_text: FullTextEnhancement,
    ) -> destiny_sdk.enhancements.FullTextEnhancement:
        """Convert to the SDK shape, signing the blob into a download URL."""
        try:
            return destiny_sdk.enhancements.FullTextEnhancement(
                enhancement_type=full_text.enhancement_type,
                file_url=await self._sign_url(
                    full_text.blob,
                    BlobSignedUrlType.DOWNLOAD,
                ),
                **full_text.model_dump(exclude={"enhancement_type", "blob"}),
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def full_text_enhancement_content_from_sdk(
        self,
        full_text_in: destiny_sdk.enhancements.FullTextEnhancement,
    ) -> FullTextEnhancement:
        """Create a FullTextEnhancement from the SDK model, hydrating blob from URL."""
        try:
            full_text = FullTextEnhancement.model_validate(
                full_text_in.model_dump(exclude={"file_url"})
                | {"blob": BlobStorageFile.from_uri(str(full_text_in.file_url))}
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return full_text

    def _demojibake_enhancement_content(
        self,
        content: destiny_sdk.enhancements.EnhancementContent,
    ) -> None:
        """In-place repair of legacy import mojibake for human display."""
        match content:
            case destiny_sdk.enhancements.BibliographicMetadataEnhancement():
                content.title = demojibake(content.title)
                content.publisher = demojibake(content.publisher)
                for author in content.authorship or []:
                    author.display_name = demojibake(author.display_name)
                if venue := content.publication_venue:
                    venue.display_name = demojibake(venue.display_name)
                    venue.host_organization_name = demojibake(
                        venue.host_organization_name
                    )
            case destiny_sdk.enhancements.AbstractContentEnhancement():
                content.abstract = demojibake(content.abstract)
            case destiny_sdk.enhancements.LinkedDataEnhancement():
                demojibake_walk(content.data, _LINKED_DATA_TEXT_KEYS)

    async def enhancement_to_sdk(
        self, enhancement: Enhancement
    ) -> destiny_sdk.references.Enhancement:
        """Convert the enhancement to an Enhancement SDK model."""
        try:
            dumped = enhancement.model_dump()
            if enhancement.content.enhancement_type == EnhancementType.FULL_TEXT:
                dumped["content"] = (
                    await self.full_text_enhancement_content_to_sdk(enhancement.content)
                ).model_dump()
            sdk_enhancement = destiny_sdk.references.Enhancement.model_validate(dumped)
            self._demojibake_enhancement_content(sdk_enhancement.content)
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception
        else:
            return sdk_enhancement

    def enhancement_from_sdk(
        self,
        enhancement_in: (
            destiny_sdk.references.Enhancement
            | destiny_sdk.enhancements.EnhancementFileInput
        ),
        reference_id: UUID | None = None,
    ) -> Enhancement:
        """Create an Enhancement from the SDK model with optional ID grafting."""
        try:
            enhancement_model = enhancement_in.model_dump()

            if enhancement_in.content.enhancement_type == EnhancementType.FULL_TEXT:
                enhancement_model["content"] = (
                    self.full_text_enhancement_content_from_sdk(
                        enhancement_in.content
                    ).model_dump()
                )

            ## The SDK isn't allowed to pass in ids or created_ats, so ignore these.
            enhancement_model.pop("id", None)
            enhancement_model.pop("created_at", None)

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
                    "reference_data_url": await self._sign_url(
                        enhancement_request.reference_data_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if enhancement_request.reference_data_file
                    else None,
                    "result_storage_url": await self._sign_url(
                        enhancement_request.result_file, BlobSignedUrlType.UPLOAD
                    )
                    if enhancement_request.result_file
                    else None,
                    "validation_result_url": await self._sign_url(
                        enhancement_request.validation_result_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if enhancement_request.validation_result_file
                    else None,
                },
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    async def search_export_to_sdk(
        self,
        search_export: SearchExport,
    ) -> destiny_sdk.references.SearchExportRead:
        """Convert the search export to the SDK model."""
        try:
            return destiny_sdk.references.SearchExportRead.model_validate(
                search_export.model_dump()
                | {
                    "result_url": await self._sign_url(
                        search_export.result_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if search_export.result_file
                    else None,
                },
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    async def reference_export_to_sdk(
        self,
        reference_export: ReferenceExport,
    ) -> destiny_sdk.references.ReferenceExportRead:
        """Convert the reference export to the SDK model."""
        try:
            return destiny_sdk.references.ReferenceExportRead.model_validate(
                reference_export.model_dump()
                | {
                    "result_url": await self._sign_url(
                        reference_export.result_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if reference_export.result_file
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
                reference_storage_url=await self._sign_url(
                    enhancement_request.reference_data_file, BlobSignedUrlType.DOWNLOAD
                )
                if enhancement_request.reference_data_file
                else None,
                result_storage_url=await self._sign_url(
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
                    "reference_data_url": await self._sign_url(
                        robot_enhancement_batch.reference_data_file,
                        BlobSignedUrlType.DOWNLOAD,
                    )
                    if robot_enhancement_batch.reference_data_file
                    else None,
                    "result_storage_url": await self._sign_url(
                        robot_enhancement_batch.result_file, BlobSignedUrlType.UPLOAD
                    )
                    if robot_enhancement_batch.result_file
                    else None,
                    "validation_result_url": await self._sign_url(
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
                reference_storage_url=await self._sign_url(
                    robot_enhancement_batch.reference_data_file,
                    BlobSignedUrlType.DOWNLOAD,
                )
                if robot_enhancement_batch.reference_data_file
                else None,
                result_storage_url=await self._sign_url(
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

    def facet_types_from_sdk(
        self,
        facets: Sequence[destiny_sdk.references.FacetType],
    ) -> list[FacetType]:
        """Map SDK facet types to their domain equivalents."""
        return [FacetType(facet.value) for facet in facets]

    def facets_to_sdk(
        self,
        buckets_by_facet: dict[FacetType, list[ESFacetBucket]],
    ) -> destiny_sdk.references.ReferenceFacetResult:
        """Convert domain facet counts into the SDK response model."""
        fields: dict[str, object] = {}
        for facet, buckets in buckets_by_facet.items():
            if facet is FacetType.CONCEPTS:
                fields["concepts"] = [
                    destiny_sdk.references.ConceptFacetCount(
                        concept=bucket.key, count=bucket.count
                    )
                    for bucket in buckets
                ]
            elif facet is FacetType.COUNTRIES:
                fields["countries"] = [
                    destiny_sdk.references.CountryFacetCount(
                        country=bucket.key, count=bucket.count
                    )
                    for bucket in buckets
                ]
            elif facet is FacetType.COUNTRY_WB_REGIONS:
                fields["country_wb_regions"] = [
                    destiny_sdk.references.CountryWBRegionFacetCount(
                        country_wb_region=bucket.key, count=bucket.count
                    )
                    for bucket in buckets
                ]
            else:
                msg = f"facets_to_sdk has no SDK mapping for FacetType.{facet.name}"
                raise NotImplementedError(msg)
        try:
            return destiny_sdk.references.ReferenceFacetResult(**fields)
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def cross_facet_to_sdk(
        self,
        cells: Sequence[CrossFacetCell],
        total: ESSearchTotal,
    ) -> destiny_sdk.references.ReferenceCrossFacetResult:
        """Convert a cross-facet result into the SDK response model."""
        try:
            return destiny_sdk.references.ReferenceCrossFacetResult(
                total={
                    "count": total.value,
                    "is_lower_bound": total.relation == "gte",
                },
                cells=[
                    destiny_sdk.references.CrossFacetCell(
                        axes=cell.axes,
                        count=cell.count,
                    )
                    for cell in cells
                ],
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    async def two_stage_reference_search_result_to_sdk(
        self,
        search_result: ESSearchResult,
        references: list[RedactedReference],
    ) -> destiny_sdk.references.ReferenceSearchResult:
        """Convert a search result and retrieved references to the SDK model."""
        try:
            hit_order = {hit.id: i for i, hit in enumerate(search_result.hits)}
            sdk_references = [
                await self.reference_to_sdk(reference)
                # Sort references according to search order
                for reference in sorted(references, key=lambda r: hit_order[r.id])
            ]
            return destiny_sdk.references.ReferenceSearchResult(
                total={
                    "count": search_result.total.value,
                    "is_lower_bound": search_result.total.relation == "gte",
                },
                page={
                    "count": len(search_result.hits),
                    "number": search_result.page,
                },
                references=sdk_references,
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def reference_id_search_result_to_sdk(
        self,
        search_result: ESSearchResult,
    ) -> destiny_sdk.references.ReferenceIDSearchResult:
        """Convert a search result to the SDK ID-only search result model."""
        try:
            return destiny_sdk.references.ReferenceIDSearchResult(
                total={
                    "count": search_result.total.value,
                    "is_lower_bound": search_result.total.relation == "gte",
                },
                reference_ids=[hit.id for hit in search_result.hits],
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

    def linked_data_concept_filter_from_query_parameter(
        self,
        concept_filter_string: str,
    ) -> LinkedDataConceptFilter:
        """
        Parse a concept filter from a query parameter.

        Values are comma-separated; each piece is stripped of surrounding
        whitespace. Empty pieces raise ``ValueError``.
        """
        concept_uris = [uri.strip() for uri in concept_filter_string.split(",")]
        if any(not uri for uri in concept_uris):
            msg = (
                "Empty concept URI in concept filter. "
                f"Got: {concept_filter_string!r}."
            )
            raise ValueError(msg)
        return LinkedDataConceptFilter(concept_uris=concept_uris)

    def linked_data_country_filter_from_query_parameter(
        self,
        country_filter_string: str,
    ) -> LinkedDataCountryFilter:
        """Parse a country filter (comma-separated ISO 3166-1 alpha-2 codes)."""
        codes = [code.strip().upper() for code in country_filter_string.split(",")]
        return LinkedDataCountryFilter(country_codes=codes)

    def linked_data_country_wb_region_filter_from_query_parameter(
        self,
        region_filter_string: str,
    ) -> LinkedDataCountryWBRegionFilter:
        """Parse a WB region filter (comma-separated region IDs)."""
        ids = [rid.strip().upper() for rid in region_filter_string.split(",")]
        return LinkedDataCountryWBRegionFilter(region_ids=ids)

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
