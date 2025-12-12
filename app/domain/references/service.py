"""The service for interacting with and managing references."""

import datetime
import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable
from uuid import UUID

from opentelemetry.trace import get_tracer

from app.core.config import (
    ESPercolationOperation,
    UploadFile,
    get_settings,
)
from app.core.exceptions import (
    DuplicateEnhancementError,
    InvalidParentEnhancementError,
    SQLNotFoundError,
)
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.models import (
    AnnotationFilter,
    DuplicateDetermination,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifier,
    ExternalIdentifierType,
    IdentifierLookup,
    LinkedExternalIdentifier,
    PendingEnhancement,
    PendingEnhancementStatus,
    PublicationYearRange,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceIds,
    ReferenceWithChangeset,
    RobotAutomation,
    RobotAutomationPercolationResult,
    RobotEnhancementBatch,
)
from app.domain.references.models.projections import DeduplicatedReferenceProjection
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.repository import (
    EnhancementRequestSQLPreloadable,
    RobotEnhancementBatchSQLPreloadable,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_service import DeduplicationService
from app.domain.references.services.enhancement_service import (
    EnhancementService,
    ProcessedResults,
)
from app.domain.references.services.search_service import SearchService
from app.domain.references.services.synchronizer_service import (
    Synchronizer,
)
from app.domain.robots.service import RobotService
from app.domain.service import GenericService
from app.persistence.blob.repository import BlobRepository
from app.persistence.blob.stream import FileStream
from app.persistence.es.persistence import ESSearchResult
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.es.uow import unit_of_work as es_unit_of_work
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work
from app.utils.lists import list_chunker
from app.utils.time_and_date import apply_positive_timedelta

logger = get_logger(__name__)
settings = get_settings()
tracer = get_tracer(__name__)


class ReferenceService(GenericService[ReferenceAntiCorruptionService]):
    """The service which manages our references."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)
        self._enhancement_service = EnhancementService(anti_corruption_service, sql_uow)
        self._deduplication_service = DeduplicationService(
            anti_corruption_service, sql_uow, es_uow
        )
        self._search_service = SearchService(anti_corruption_service, sql_uow, es_uow)
        self._synchronizer = Synchronizer(sql_uow, es_uow)

    @sql_unit_of_work
    async def get_reference(self, reference_id: UUID) -> Reference:
        """Get a single reference by id."""
        return await self._get_reference(reference_id)

    async def _get_reference(self, reference_id: UUID) -> Reference:
        """Get a single reference by id without using the unit of work."""
        # This method is used internally and does not use the unit of work.
        return await self.sql_uow.references.get_by_pk(
            reference_id, preload=["identifiers", "enhancements"]
        )

    async def _get_deduplicated_references(
        self,
        reference_ids: Collection[UUID] | None = None,
        references: Collection[Reference] | None = None,
    ) -> list[Reference]:
        """
        Get the deduplicated reference for a given reference.

        :param reference_ids: The ID of the references to get the deduplicated view for.
        :type reference_ids: Collection[UUID] | None
        :param references: The references to get the deduplicated view for. Must have]
            identifiers, enhancements, duplicate_decision and duplicate_references
            preloaded.
        :type references: Collection[Reference] | None
        :return: The deduplicated reference.
        :rtype: Reference
        """
        if bool(reference_ids) == bool(references):
            msg = "Exactly one of reference_ids or references must be provided."
            raise ValueError(msg)

        if reference_ids:
            references = await self.sql_uow.references.get_by_pks(
                reference_ids,
                preload=[
                    "identifiers",
                    "enhancements",
                    "duplicate_decision",
                    "duplicate_references",
                ],
            )
        if not references:
            return []
        return [
            DeduplicatedReferenceProjection.get_from_reference(reference)
            for reference in references
        ]

    async def _get_deduplicated_reference(self, reference_id: UUID) -> Reference:
        """
        Get the deduplicated reference for a given reference.

        :param reference_id: The ID of the reference to get the deduplicated view for.
        :type reference_id: UUID
        :return: The deduplicated reference.
        :rtype: Reference
        """
        return (await self._get_deduplicated_references([reference_id]))[0]

    async def _get_deduplicated_canonical_reference(
        self, reference_id: UUID
    ) -> Reference:
        """
        Get the deduplicated canonical reference for a given reference ID.

        If the given reference is a duplicate, this will return the deduplicated view
        of its canonical reference.

        :param reference_id: The ID of the reference to get the deduplicated view for.
        :type reference_id: UUID
        """
        reference = await self.sql_uow.references.get_by_pk(
            reference_id,
            preload=["duplicate_decision"],
        )

        if reference.canonical_like:
            return await self._get_deduplicated_reference(reference.id)

        if (
            not reference.duplicate_decision
            or not reference.duplicate_decision.canonical_reference_id
        ):
            msg = (
                "Reference is not canonical but has no canonical reference id. "
                "This should not happen."
            )
            raise RuntimeError(msg)

        return await self._get_deduplicated_canonical_reference(
            reference.duplicate_decision.canonical_reference_id
        )

    async def _get_deduplicated_canonical_references(
        self,
        reference_ids: Collection[UUID] | None = None,
        references: Collection[Reference] | None = None,
    ) -> list[Reference]:
        """
        Get the deduplicated canonical references for a list of reference IDs.

        Only one of reference_ids or references should be provided.

        :param reference_ids: The references to get the deduplicated view for.
        :type reference_ids: Collection[UUID] | None
        :param references: The references with duplicate_decision preloaded to get the
            deduplicated view for.
        :type references: Collection[Reference] | None
        :return: The deduplicated canonical references.
        :rtype: list[Reference]
        """
        if bool(reference_ids) == bool(references):
            msg = "Exactly one of reference_ids or references must be provided."
            raise ValueError(msg)

        if reference_ids:
            references = await self.sql_uow.references.get_by_pks(
                reference_ids,
                preload=[
                    "identifiers",
                    "enhancements",
                    "duplicate_decision",
                    "duplicate_references",
                ],
            )

        if not references:
            return []

        canonical_references, duplicate_canonical_ids = [], []
        for reference in references:
            if reference.canonical_like:
                canonical_references.append(reference)
            else:
                if (
                    not reference.duplicate_decision
                    or not reference.duplicate_decision.canonical_reference_id
                ):
                    msg = (
                        "Reference is not canonical but has no canonical reference id. "
                        "This should not happen."
                    )
                    raise RuntimeError(msg)
                duplicate_canonical_ids.append(
                    reference.duplicate_decision.canonical_reference_id
                )

        canonical_references = await self._get_deduplicated_references(
            references=canonical_references
        )

        if duplicate_canonical_ids:
            canonical_references += await self._get_deduplicated_canonical_references(
                reference_ids=duplicate_canonical_ids,
            )

        return canonical_references

    async def _get_canonical_reference_with_implied_changeset(
        self, reference_id: UUID
    ) -> ReferenceWithChangeset:
        """
        Get a canonical reference with its implied changeset per its duplicate decision.

        This is used after a duplicate decision as an automation trigger.

        If a reference is canonical, its implied changeset is itself.
        If a reference is a duplicate, its implied changeset is again itself, but the
        base reference is the deduplicated projection of its canonical reference.
        """
        reference = await self.sql_uow.references.get_by_pk(
            reference_id, preload=["identifiers", "enhancements", "duplicate_decision"]
        )
        deduplicated_canonical_reference = (
            await self._get_deduplicated_canonical_reference(reference_id)
        )
        return ReferenceWithChangeset(
            **deduplicated_canonical_reference.model_dump(),
            changeset=reference,
        )

    @sql_unit_of_work
    async def get_canonical_reference_with_implied_changeset(
        self, reference_id: UUID
    ) -> ReferenceWithChangeset:
        """Get a canonical reference with its implied changeset per its duplicate decision."""  # noqa: E501
        return await self._get_canonical_reference_with_implied_changeset(reference_id)

    async def _merge_reference(self, reference: Reference) -> Reference:
        """Persist a reference with an existing SQL & ES UOW."""
        db_reference = await self.sql_uow.references.merge(reference)
        await self._synchronizer.references.sql_to_es(db_reference.id)
        return db_reference

    @sql_unit_of_work
    @es_unit_of_work
    async def merge_reference(self, reference: Reference) -> Reference:
        """Persist a reference."""
        return await self._merge_reference(reference)

    async def _add_enhancement(self, enhancement: Enhancement) -> Reference:
        """
        Add an enhancement to a reference.

        :param enhancement: The enhancement to add
        :type enhancement: Enhancement
        """
        reference = await self.sql_uow.references.get_by_pk(
            enhancement.reference_id,
            preload=["enhancements", "identifiers", "duplicate_references"],
        )

        incoming_enhancement_hash = enhancement.hash_data()
        for existing_enhancement in reference.enhancements or []:
            if existing_enhancement.hash_data() == incoming_enhancement_hash:
                detail = (
                    "An exact duplicate enhancement already exists on this reference."
                )
                raise DuplicateEnhancementError(detail)

        if enhancement.derived_from:
            valid_derived_reference_ids = {
                ref.id for ref in reference.duplicate_references or []
            } | {reference.id}
            try:
                parent_enhancements = await self.sql_uow.enhancements.get_by_pks(
                    enhancement.derived_from
                )
                if not all(
                    e.reference_id in valid_derived_reference_ids
                    for e in parent_enhancements
                ):
                    detail = (
                        "All parent enhancements must belong to the same reference "
                        "tree as the child enhancement."
                    )
                    raise InvalidParentEnhancementError(detail)
            except SQLNotFoundError as e:
                detail = f"Enhancements with ids {e.lookup_value} do not exist."
                raise InvalidParentEnhancementError(detail) from e

        # This uses SQLAlchemy to treat References as an aggregate of enhancements.
        # All considered this is a naive implementation, but it works for now.
        reference.enhancements = [*(reference.enhancements or []), *[enhancement]]
        return await self.sql_uow.references.merge(reference)

    @sql_unit_of_work
    async def add_enhancement(self, enhancement: Enhancement) -> Reference:
        """Add an enhancement to a reference."""
        return await self._add_enhancement(enhancement)

    async def _get_hydrated_references(
        self,
        reference_ids: list[UUID],
        enhancement_types: list[EnhancementType] | None = None,
        external_identifier_types: list[ExternalIdentifierType] | None = None,
    ) -> list[Reference]:
        """Get a list of references with enhancements and identifiers by id."""
        return await self.sql_uow.references.get_hydrated(
            reference_ids,
            enhancement_types=[
                enhancement_type.value for enhancement_type in enhancement_types
            ]
            if enhancement_types
            else None,
            external_identifier_types=[
                external_identifier_type.value
                for external_identifier_type in external_identifier_types
            ]
            if external_identifier_types
            else None,
        )

    async def _get_jsonl_hydrated_references(
        self,
        reference_ids: list[UUID],
    ) -> list[str]:
        """Get a list of JSONL strings for hydrated references by id."""
        return [
            self._anti_corruption_service.reference_to_sdk(ref).to_jsonl()
            for ref in await self._get_hydrated_references(reference_ids)
        ]

    @sql_unit_of_work
    async def get_all_reference_ids(self) -> list[UUID]:
        """Get all reference IDs from the database."""
        return await self.sql_uow.references.get_all_pks()

    @sql_unit_of_work
    async def get_references_from_identifiers(
        self, identifiers: list[IdentifierLookup]
    ) -> list[Reference]:
        """Get a list of references from identifiers."""
        external_identifiers, db_identifiers = [], []
        for identifier in identifiers:
            if identifier.identifier_type:
                external_identifiers.append(identifier)
            else:
                db_identifiers.append(uuid.UUID(identifier.identifier))

        references = await self.sql_uow.references.find_with_identifiers(
            external_identifiers,
            preload=[
                "identifiers",
                "enhancements",
                "duplicate_decision",
                "duplicate_references",
            ],
            match="any",
        ) + await self.sql_uow.references.get_by_pks(
            db_identifiers,
            preload=[
                "identifiers",
                "enhancements",
                "duplicate_decision",
                "duplicate_references",
            ],
            fail_on_missing=False,
        )
        if not references:
            return []

        # Pre-filter duplicates
        references = list(
            {reference.id: reference for reference in references}.values()
        )
        references = await self._get_deduplicated_canonical_references(
            references=references
        )
        # Filter again in case multiple duplicates pointed to same canonical
        return list({reference.id: reference for reference in references}.values())

    @sql_unit_of_work
    async def add_identifier(
        self, reference_id: UUID, identifier: ExternalIdentifier
    ) -> LinkedExternalIdentifier:
        """Register an identifier, persisting it to the database."""
        reference = await self.sql_uow.references.get_by_pk(reference_id)
        db_identifier = LinkedExternalIdentifier(
            reference_id=reference.id,
            identifier=identifier,
        )
        return await self.sql_uow.external_identifiers.add(db_identifier)

    @sql_unit_of_work
    @es_unit_of_work
    async def ingest_reference(
        self, record_str: str, entry_ref: int
    ) -> ReferenceCreateResult:
        """Ingest a reference from a file."""
        # Full deduplication flow
        reference_create_result = ReferenceCreateResult.from_raw(record_str, entry_ref)
        if not reference_create_result.reference:
            return reference_create_result
        reference = self._anti_corruption_service.reference_from_sdk_file_input(
            reference_create_result.reference
        )
        reference_create_result.reference_id = reference.id
        trace_attribute(Attributes.REFERENCE_ID, str(reference.id))

        canonical_reference = await self._deduplication_service.find_exact_duplicate(
            reference
        )
        if canonical_reference:
            logger.info(
                "Exact duplicate found during ingestion",
                reference_id=str(reference.id),
                canonical_reference_id=str(canonical_reference.id),
            )
            await self._deduplication_service.register_duplicate_decision_for_reference(
                reference_id=reference.id,
                duplicate_determination=DuplicateDetermination.EXACT_DUPLICATE,
                canonical_reference_id=canonical_reference.id,
            )
            return reference_create_result

        duplicate_decision = (
            await self._deduplication_service.register_duplicate_decision_for_reference(
                reference_id=reference.id
            )
        )
        await self._merge_reference(reference)
        reference_create_result.duplicate_decision_id = duplicate_decision.id

        return reference_create_result

    @sql_unit_of_work
    async def register_reference_enhancement_request(
        self,
        enhancement_request: EnhancementRequest,
    ) -> EnhancementRequest:
        """Create an enhancement request."""
        await self.sql_uow.references.verify_pk_existence(
            enhancement_request.reference_ids
        )

        await self.sql_uow.enhancement_requests.add(enhancement_request)

        await self._create_pending_enhancements(
            robot_id=enhancement_request.robot_id,
            reference_ids=enhancement_request.reference_ids,
            enhancement_request_id=enhancement_request.id,
        )

        return enhancement_request

    async def _create_pending_enhancements(
        self,
        robot_id: UUID,
        reference_ids: Iterable[UUID],
        enhancement_request_id: UUID | None = None,
        source: str | None = None,
    ) -> list[PendingEnhancement]:
        """Create a batch enhancement request."""
        pending_enhancements_to_create = [
            PendingEnhancement(
                reference_id=ref_id,
                robot_id=robot_id,
                enhancement_request_id=enhancement_request_id,
                source=source,
            )
            for ref_id in reference_ids
        ]

        if pending_enhancements_to_create:
            return await self.sql_uow.pending_enhancements.add_bulk(
                pending_enhancements_to_create
            )

        return []

    @sql_unit_of_work
    async def create_pending_enhancements(
        self,
        robot_id: UUID,
        reference_ids: Iterable[UUID],
        enhancement_request_id: UUID | None = None,
        source: str | None = None,
    ) -> list[PendingEnhancement]:
        """Create pending enhancements."""
        return await self._create_pending_enhancements(
            robot_id=robot_id,
            reference_ids=reference_ids,
            enhancement_request_id=enhancement_request_id,
            source=source,
        )

    @sql_unit_of_work
    async def expire_and_replace_stale_pending_enhancements(
        self,
        max_retry_count: int = 3,
    ) -> dict[str, int]:
        """
        Expire stale pending enhancements and create replacements.

        Searches for PendingEnhancements with expired leases and:
        1. Moves them to EXPIRED status
        2. Creates new PendingEnhancements as replacements (if retry limit not reached)
        3. Populates the retry_of field to link to the expired enhancement

        Args:
            max_retry_count: Maximum number of retries allowed (default: 3)

        Returns:
            Dictionary with counts of expired and replaced_with pending enhancements

        """
        now = datetime.datetime.now(tz=datetime.UTC)
        repo = self.sql_uow.pending_enhancements
        expired_enhancements = await repo.expire_pending_enhancements_past_expiry(
            now=now,
            statuses=[
                PendingEnhancementStatus.PROCESSING,
            ],
        )

        if not expired_enhancements:
            logger.info("No stale pending enhancements found")
            return {"expired": 0, "replaced_with": 0}

        logger.info(
            "Found stale pending enhancements",
            count=len(expired_enhancements),
        )

        new_pending_enhancements = (
            await self._enhancement_service.create_retry_pending_enhancements(
                expired_enhancements,
                max_retry_count,
            )
        )

        if new_pending_enhancements:
            logger.info(
                "Created new pending enhancements for retry",
                count=len(new_pending_enhancements),
            )

        return {
            "expired": len(expired_enhancements),
            "replaced_with": len(new_pending_enhancements),
        }

    @sql_unit_of_work
    async def get_enhancement_request(
        self,
        enhancement_request_id: UUID,
        preload: list[EnhancementRequestSQLPreloadable] | None = None,
    ) -> EnhancementRequest:
        """Get a batch enhancement request by request id."""
        return await self.sql_uow.enhancement_requests.get_by_pk(
            enhancement_request_id, preload=preload
        )

    async def _get_robot_enhancement_batch(
        self,
        robot_enhancement_batch_id: UUID,
        preload: list[RobotEnhancementBatchSQLPreloadable] | None = None,
    ) -> RobotEnhancementBatch:
        """Get a robot enhancement batch by batch id."""
        return await self.sql_uow.robot_enhancement_batches.get_by_pk(
            robot_enhancement_batch_id, preload=preload
        )

    @sql_unit_of_work
    async def get_robot_enhancement_batch(
        self,
        robot_enhancement_batch_id: UUID,
        preload: list[RobotEnhancementBatchSQLPreloadable] | None = None,
    ) -> RobotEnhancementBatch:
        """Get a robot enhancement batch by batch id."""
        return await self._get_robot_enhancement_batch(
            robot_enhancement_batch_id, preload=preload
        )

    @sql_unit_of_work
    async def get_enhancement_request_with_calculated_status(
        self,
        enhancement_request_id: UUID,
    ) -> EnhancementRequest:
        """Get an enhancement request with calculated status."""
        return await self.sql_uow.enhancement_requests.get_by_pk(
            enhancement_request_id, preload=["status"]
        )

    async def handle_enhancement_result_entry(
        self,
        enhancement: Enhancement,
    ) -> tuple[PendingEnhancementStatus, str]:
        """Handle the import of a single batch enhancement result entry."""
        try:
            await self._add_enhancement(enhancement)
        except SQLNotFoundError:
            return (
                PendingEnhancementStatus.FAILED,
                "Reference does not exist.",
            )
        except DuplicateEnhancementError:
            return (
                PendingEnhancementStatus.DISCARDED,
                "Exact duplicate enhancement already exists on reference.",
            )
        except Exception:
            logger.exception(
                "Failed to add enhancement to reference.",
                reference_id=enhancement.reference_id,
                enhancement=enhancement,
            )
            return (
                PendingEnhancementStatus.FAILED,
                "Failed to add enhancement to reference.",
            )

        return (
            PendingEnhancementStatus.COMPLETED,
            "Enhancement added.",
        )

    @sql_unit_of_work
    async def validate_and_import_robot_enhancement_batch_result(
        self,
        robot_enhancement_batch: RobotEnhancementBatch,
        blob_repository: BlobRepository,
    ) -> ProcessedResults:
        """
        Validate and import the result of a robot enhancement batch.

        This process:
        - streams the result of the robot enhancement batch line-by-line
        - adds the enhancement to the database
        - streams the validation result to the blob storage service line-by-line
        - does some final validation of missing references and updates the request
        """
        if not robot_enhancement_batch.result_file:
            msg = "Robot enhancement batch has no result file. This should not happen."
            raise RuntimeError(msg)

        pending_enhancements = robot_enhancement_batch.pending_enhancements
        if not pending_enhancements:
            pending_enhancements = await self.sql_uow.pending_enhancements.find(
                robot_enhancement_batch_id=robot_enhancement_batch.id
            )

        # Mutable sets to track imported enhancement IDs and pending enhancement IDs
        results = ProcessedResults(
            imported_enhancement_ids=set(),
            successful_pending_enhancement_ids=set(),
            failed_pending_enhancement_ids=set(),
            discarded_pending_enhancement_ids=set(),
        )

        validation_result_file = await blob_repository.upload_file_to_blob_storage(
            content=FileStream(
                generator=self._enhancement_service.process_robot_enhancement_batch_result(
                    blob_repository=blob_repository,
                    result_file=robot_enhancement_batch.result_file,
                    pending_enhancements=pending_enhancements,
                    add_enhancement=self.handle_enhancement_result_entry,
                    results=results,
                )
            ),
            path="enhancement_result",
            filename=f"{robot_enhancement_batch.id}_repo.jsonl",
        )

        await self._enhancement_service.add_validation_result_file_to_robot_enhancement_batch(  # noqa: E501
            robot_enhancement_batch.id, validation_result_file
        )

        return results

    @sql_unit_of_work
    async def mark_robot_enhancement_batch_failed(
        self,
        robot_enhancement_batch_id: UUID,
        error: str,
    ) -> RobotEnhancementBatch:
        """Mark a robot enhancement batch as failed and supply error message."""
        return await self._enhancement_service.mark_robot_enhancement_batch_failed(
            robot_enhancement_batch_id, error
        )

    @sql_unit_of_work
    async def update_enhancement_request_status(
        self,
        enhancement_request_id: UUID,
        status: EnhancementRequestStatus,
    ) -> EnhancementRequest:
        """Update a batch enhancement request."""
        return await self._enhancement_service.update_enhancement_request_status(
            enhancement_request_id, status
        )

    @sql_unit_of_work
    async def update_pending_enhancements_status(
        self,
        pending_enhancement_ids: list[UUID],
        status: PendingEnhancementStatus,
    ) -> int:
        """Update pending enhancements status."""
        return await self._enhancement_service.update_pending_enhancements_status(
            pending_enhancement_ids, status
        )

    @sql_unit_of_work
    async def update_pending_enhancements_status_for_robot_enhancement_batch(
        self,
        robot_enhancement_batch_id: UUID,
        status: PendingEnhancementStatus,
    ) -> int:
        """Update pending enhancements status for a robot enhancement batch."""
        pending_enhancements = await self.sql_uow.pending_enhancements.find(
            robot_enhancement_batch_id=robot_enhancement_batch_id
        )

        if pending_enhancements:
            return await self._enhancement_service.update_pending_enhancements_status(
                [pe.id for pe in pending_enhancements], status
            )

        return 0

    @sql_unit_of_work
    @es_unit_of_work
    async def index_references(
        self,
        reference_ids: Iterable[UUID],
    ) -> None:
        """Index references in Elasticsearch."""
        await self._synchronizer.references.bulk_sql_to_es(reference_ids)

    async def repopulate_reference_index(self) -> None:
        """Index ALL references in Elasticsearch."""
        reference_ids = await self.get_all_reference_ids()
        await self.index_references(reference_ids)

    async def _get_reference_changesets_from_enhancements(
        self,
        enhancement_ids: list[UUID],
    ) -> list[ReferenceWithChangeset]:
        """
        Get the reference changeset from an incoming enhancement.

        This is a temporary adapter, to eventually be superseded by direct passing of
        ReferenceWithChangeset from the enhancing process.
        See the note in docstring of detect_robot_automations().
        """
        enhancements = await self.sql_uow.enhancements.get_by_pks(enhancement_ids)
        # Enhancements are always automated against the references they're imported on.
        # In most cases this will be the canonical reference, triggered by automation.
        # Some edge cases exist where enhancements are added to duplicates, and so we
        # automate on the duplicate. See the robot automation procedure docs for more.

        deduplicated_references: list[
            Reference
        ] = await self._get_deduplicated_references(
            [enhancement.reference_id for enhancement in enhancements]
        )
        return [
            ReferenceWithChangeset(
                **reference.model_dump(),
                changeset=Reference(
                    id=enhancement.reference_id,
                    enhancements=[enhancement],
                ),
            )
            for enhancement, reference in zip(
                enhancements, deduplicated_references, strict=True
            )
        ]

    async def _detect_robot_automations(
        self,
        reference: ReferenceWithChangeset | None = None,
        enhancement_ids: Iterable[UUID] | None = None,
    ) -> list[RobotAutomationPercolationResult]:
        """Detect and dispatch robot automations for an added reference/enhancement."""
        robot_automations: list[RobotAutomationPercolationResult] = []

        if reference:
            robot_automations.extend(
                await self.es_uow.robot_automations.percolate([reference])
            )
        if enhancement_ids:
            for enhancement_id_chunk in list_chunker(
                list(enhancement_ids),
                settings.es_percolation_chunk_size_override.get(
                    ESPercolationOperation.ROBOT_AUTOMATION,
                    settings.default_es_percolation_chunk_size,
                ),
            ):
                robot_automations.extend(
                    await self.es_uow.robot_automations.percolate(
                        await self._get_reference_changesets_from_enhancements(
                            enhancement_id_chunk
                        )
                    )
                )

        # Merge robot_automations on robot_id
        robot_automations_dict: dict[UUID, set[UUID]] = defaultdict(set)
        for automation in robot_automations:
            robot_automations_dict[automation.robot_id] |= automation.reference_ids

        return [
            RobotAutomationPercolationResult(
                robot_id=robot_id,
                reference_ids=list(reference_ids),
            )
            for robot_id, reference_ids in robot_automations_dict.items()
        ]

    @es_unit_of_work
    @sql_unit_of_work
    async def detect_robot_automations(
        self,
        reference: ReferenceWithChangeset | None = None,
        enhancement_ids: Iterable[UUID] | None = None,
    ) -> list[RobotAutomationPercolationResult]:
        """
        Detect robot automations for a set of references or enhancements.

        NB this is currently in a bit of an asymmetric state. Imports are processed
        per-reference, and enhancement fulfillments are processed per-batch. If/when we
        process enhancements per-reference, then the enhancement_ids parameter and
        translation can be removed in favour of directly passing in a
        ReferenceWithChangeset.
        """
        return await self._detect_robot_automations(
            reference=reference, enhancement_ids=enhancement_ids
        )

    @sql_unit_of_work
    @es_unit_of_work
    async def repopulate_robot_automation_percolation_index(
        self,
    ) -> None:
        """
        Repopulate the robot automation percolation index.

        We assume the scale is small enough that we can do this naively.
        """
        for robot_automation in await self.sql_uow.robot_automations.get_all():
            await self._synchronizer.robot_automations.sql_to_es(robot_automation.id)

    @sql_unit_of_work
    async def get_robot_automations(self) -> list[RobotAutomation]:
        """Get all robot automations."""
        return await self.sql_uow.robot_automations.get_all()

    @sql_unit_of_work
    async def get_robot_automation(self, automation_id: UUID) -> RobotAutomation:
        """Get a robot automation by id."""
        return await self.sql_uow.robot_automations.get_by_pk(automation_id)

    @sql_unit_of_work
    @es_unit_of_work
    async def add_robot_automation(
        self, robot_service: RobotService, automation: RobotAutomation
    ) -> RobotAutomation:
        """Add a robot automation."""
        # Check existence first
        await robot_service.get_robot(automation.robot_id)

        # We do the indexing inside the SQL UoW as the ES indexing actually provides
        # some handy validation against the index itself. This is caught with an API-
        # level exception handler, so we don't need to handle it here.
        await self.sql_uow.robot_automations.add(automation)
        return await self._synchronizer.robot_automations.sql_to_es(automation.id)

    @sql_unit_of_work
    @es_unit_of_work
    async def update_robot_automation(
        self,
        automation: RobotAutomation,
        robot_service: RobotService,
    ) -> RobotAutomation:
        """Update a robot automation."""
        # Check existence first
        await self.sql_uow.robot_automations.get_by_pk(automation.id)
        await robot_service.get_robot(automation.robot_id)

        # We do the indexing inside the SQL UoW as the ES indexing actually provides
        # some handy validation against the index itself. This is caught with an API-
        # level exception handler, so we don't need to handle it here.
        automation = await self.sql_uow.robot_automations.merge(automation)
        return await self._synchronizer.robot_automations.sql_to_es(automation.id)

    @sql_unit_of_work
    async def get_reference_duplicate_decision(
        self,
        reference_duplicate_decision_id: UUID,
    ) -> ReferenceDuplicateDecision:
        """Get a reference duplicate decision by id."""
        return await self.sql_uow.reference_duplicate_decisions.get_by_pk(
            reference_duplicate_decision_id
        )

    async def apply_reference_duplicate_decision_side_effects(
        self,
        reference_duplicate_decision: ReferenceDuplicateDecision,
        *,
        decision_changed: bool,
    ) -> ReferenceDuplicateDecision:
        """
        Apply side-effects of a reference duplicate decision.

        This reprojects the deduplicated reference to ES, and triggers any robot
        automations if the decision has changed.
        """
        if reference_duplicate_decision.active_decision:
            await self._synchronizer.references.sql_to_es(
                reference_duplicate_decision.reference_id
            )
            if decision_changed:
                reference = await self._get_canonical_reference_with_implied_changeset(
                    reference_duplicate_decision.reference_id
                )
                await self.detect_and_dispatch_robot_automations(
                    reference=reference,
                    source_str=f"DuplicateDecision:{reference_duplicate_decision.id}",
                )
        return reference_duplicate_decision

    @sql_unit_of_work
    @es_unit_of_work
    async def process_reference_duplicate_decision(
        self,
        reference_duplicate_decision: ReferenceDuplicateDecision,
    ) -> None:
        """Process a reference duplicate decision."""
        if settings.trusted_unique_identifier_types:
            shortcutted_decisions = await self._deduplication_service.shortcut_deduplication_using_identifiers(  # noqa: E501
                reference_duplicate_decision,
                settings.trusted_unique_identifier_types,
            )
            if shortcutted_decisions:
                for decision in shortcutted_decisions:
                    await self.apply_reference_duplicate_decision_side_effects(
                        decision,
                        decision_changed=True,
                    )
                return

        # Carry on with normal processing
        reference_duplicate_decision = (
            await self._deduplication_service.nominate_candidate_canonicals(
                reference_duplicate_decision
            )
        )

        reference_duplicate_decision = (
            await self._deduplication_service.determine_canonical_from_candidates(
                reference_duplicate_decision
            )
        )

        (
            reference_duplicate_decision,
            decision_changed,
        ) = await self._deduplication_service.map_duplicate_decision(
            reference_duplicate_decision
        )

        await self.apply_reference_duplicate_decision_side_effects(
            reference_duplicate_decision,
            decision_changed=decision_changed,
        )

    @sql_unit_of_work
    async def get_pending_enhancements_for_robot(
        self, robot_id: UUID, limit: int
    ) -> list[PendingEnhancement]:
        """Get pending enhancements for a robot."""
        pending_enhancements = await self.sql_uow.pending_enhancements.find(
            robot_id=robot_id,
            robot_enhancement_batch_id=None,
            status=PendingEnhancementStatus.PENDING,
            order_by="created_at",
            limit=limit,
        )

        # There is a restriction in EnhancementService._categorize_enhancements
        # that reference IDs are unique per batch. The below adapter is a band-aid to
        # enforce that restriction here. Any pending enhancements beyond the first for a
        # given reference ID are filtered out, and hence not accepted, and can be picked
        # up in a future batch.
        # See https://github.com/destiny-evidence/destiny-repository/issues/353.
        return list(
            {pe.reference_id: pe for pe in reversed(pending_enhancements)}.values()
        )

    @sql_unit_of_work
    async def create_robot_enhancement_batch(
        self,
        robot_id: UUID,
        pending_enhancements: list[PendingEnhancement],
        lease_duration: datetime.timedelta,
        blob_repository: BlobRepository,
    ) -> RobotEnhancementBatch:
        """
        Create a robot enhancement batch.

        Args:
            robot_id (UUID): The ID of the robot.
            pending_enhancements (list[PendingEnhancement]): The list of pending
                enhancements to include in the batch.
            blob_repository (BlobRepository): The blob repository.

        Returns:
            RobotEnhancementBatch: The created robot enhancement batch.

        """
        robot_enhancement_batch = RobotEnhancementBatch(robot_id=robot_id)

        await self.sql_uow.robot_enhancement_batches.add(robot_enhancement_batch)

        pending_enhancement_ids = [pe.id for pe in pending_enhancements]
        if pending_enhancement_ids:
            await self.sql_uow.pending_enhancements.bulk_update(
                pks=pending_enhancement_ids,
                status=PendingEnhancementStatus.PROCESSING,
                robot_enhancement_batch_id=robot_enhancement_batch.id,
                expires_at=apply_positive_timedelta(lease_duration),
            )

        file_stream = FileStream(
            self._get_jsonl_hydrated_references,
            [
                {
                    "reference_ids": reference_id_chunk,
                }
                for reference_id_chunk in list_chunker(
                    [p.reference_id for p in pending_enhancements],
                    settings.upload_file_chunk_size_override.get(
                        UploadFile.ROBOT_ENHANCEMENT_REFERENCE_DATA,
                        settings.default_upload_file_chunk_size,
                    ),
                )
            ],
        )

        reference_data_file = await blob_repository.upload_file_to_blob_storage(
            content=file_stream,
            path="robot_enhancement_batch_reference_data",
            filename=f"{robot_enhancement_batch.id}.jsonl",
        )

        return await self._enhancement_service.build_robot_enhancement_batch(
            robot_enhancement_batch=robot_enhancement_batch,
            reference_data_file=reference_data_file,
        )

    @sql_unit_of_work
    async def renew_robot_enhancement_batch_lease(
        self,
        robot_enhancement_batch_id: UUID,
        lease_duration: datetime.timedelta,
    ) -> tuple[int, datetime.datetime]:
        """Renew a robot enhancement batch lease."""
        await self.sql_uow.robot_enhancement_batches.verify_pk_existence(
            [robot_enhancement_batch_id]
        )
        expiry = apply_positive_timedelta(lease_duration)
        updated = await self.sql_uow.pending_enhancements.bulk_update_by_filter(
            filter_conditions={
                "robot_enhancement_batch_id": robot_enhancement_batch_id,
                # If a robot lets a pending enhancement expire, it must use a
                # new robot enhancement batch to re-process it.
                "status": PendingEnhancementStatus.PROCESSING,
            },
            expires_at=expiry,
        )
        return updated, expiry

    @sql_unit_of_work
    async def invoke_deduplication_for_references(
        self,
        reference_ids: ReferenceIds,
    ) -> None:
        """Invoke deduplication for a list of references."""
        reference_duplicate_decisions = (
            await self.sql_uow.reference_duplicate_decisions.add_bulk(
                [
                    ReferenceDuplicateDecision(
                        reference_id=reference_id,
                        duplicate_determination=DuplicateDetermination.PENDING,
                    )
                    for reference_id in reference_ids.reference_ids
                ]
            )
        )
        for decision in reference_duplicate_decisions:
            await queue_task_with_trace(
                ("app.domain.references.tasks", "process_reference_duplicate_decision"),
                reference_duplicate_decision_id=decision.id,
                otel_enabled=settings.otel_enabled,
            )

    @es_unit_of_work
    async def search_references(
        self,
        query: str,
        page: int = 1,
        annotations: list[AnnotationFilter] | None = None,
        publication_year_range: PublicationYearRange | None = None,
        sort: list[str] | None = None,
    ) -> ESSearchResult[Reference]:
        """Search for references given a query string."""
        return await self._search_service.search_with_query_string(
            query,
            page=page,
            annotations=annotations,
            publication_year_range=publication_year_range,
            sort=sort,
        )

    @tracer.start_as_current_span("Detect and dispatch robot automations")
    async def detect_and_dispatch_robot_automations(
        self,
        reference: ReferenceWithChangeset | None = None,
        enhancement_ids: Iterable[uuid.UUID] | None = None,
        source_str: str | None = None,
        skip_robot_id: uuid.UUID | None = None,
    ) -> None:
        """
        Request default enhancements for a set of references.

        Technically this is a task distributor, not a task - may live in a higher layer
        later in life.

        NB this is in a transient state, see comments in
        ReferenceService.detect_robot_automations.
        """
        robot_automations = await self._detect_robot_automations(
            reference=reference,
            enhancement_ids=enhancement_ids,
        )
        for robot_automation in robot_automations:
            if robot_automation.robot_id == skip_robot_id:
                logger.warning(
                    "Detected robot automation loop, skipping."
                    " This is likely a problem in the percolation query.",
                    robot_id=str(robot_automation.robot_id),
                    source=source_str,
                )
                continue
            await self._create_pending_enhancements(
                robot_id=robot_automation.robot_id,
                reference_ids=robot_automation.reference_ids,
                source=source_str,
            )
