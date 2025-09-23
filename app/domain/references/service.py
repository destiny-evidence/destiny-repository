"""The service for interacting with and managing references."""

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from app.core.config import (
    ESPercolationOperation,
    UploadFile,
    get_settings,
)
from app.core.exceptions import (
    InvalidParentEnhancementError,
    RobotEnhancementError,
    RobotUnreachableError,
    SQLNotFoundError,
)
from app.core.telemetry.logger import get_logger
from app.domain.imports.models.models import CollisionStrategy
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifier,
    ExternalIdentifierSearch,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceWithChangeset,
    RobotAutomation,
    RobotAutomationPercolationResult,
)
from app.domain.references.models.projections import DeduplicatedReferenceProjection
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_service import DeduplicationService
from app.domain.references.services.enhancement_service import (
    EnhancementService,
)
from app.domain.references.services.ingestion_service import (
    IngestionService,
)
from app.domain.references.services.synchronizer_service import (
    Synchronizer,
)
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher
from app.domain.robots.service import RobotService
from app.domain.service import GenericService
from app.persistence.blob.repository import BlobRepository
from app.persistence.blob.stream import FileStream
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.es.uow import unit_of_work as es_unit_of_work
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work
from app.utils.lists import list_chunker

logger = get_logger(__name__)
settings = get_settings()


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
        self._ingestion_service = IngestionService(anti_corruption_service, sql_uow)
        self._enhancement_service = EnhancementService(anti_corruption_service, sql_uow)
        self._deduplication_service = DeduplicationService(
            anti_corruption_service, sql_uow
        )
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

    async def _get_canonical_reference(self, reference_id: UUID) -> Reference:
        """Get the canonical reference for a given reference."""
        reference = await self.sql_uow.references.get_by_pk(
            reference_id,
            preload=[
                "identifiers",
                "enhancements",
                "duplicate_decision",
                "duplicate_references",
            ],
        )
        if reference.canonical_like:
            return DeduplicatedReferenceProjection.get_from_reference(reference)

        if (
            not reference.duplicate_decision
            or not reference.duplicate_decision.canonical_reference_id
        ):
            msg = (
                "Reference is not canonical but has no canonical reference id. "
                "This should not happen."
            )
            raise RuntimeError(msg)

        return await self._get_canonical_reference(
            reference.duplicate_decision.canonical_reference_id
        )

    @sql_unit_of_work
    async def get_canonical_reference_with_implied_changeset(
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
        canonical_reference = await self._get_canonical_reference(reference_id)
        return ReferenceWithChangeset(
            **DeduplicatedReferenceProjection.get_from_reference(
                canonical_reference
            ).model_dump(),
            delta_reference=reference,
        )

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

    async def _add_enhancement(
        self, enhancement: Enhancement, *, enforce_enhancement_tree: bool = True
    ) -> Reference:
        """
        Add an enhancement to a reference.

        :param enhancement: The enhancement to add
        :type enhancement: Enhancement
        :param enforce_enhancement_tree: Whether the enhancement's parents must be
        from the same reference. If False, will still verify the enhancement's
        parents exist without the ownership check. This should be True unless you have
        a good reason not to. An example of a good reason is duplicating an enhancement
        to another reference, which should point back at the source enhancement.
        :type enforce_enhancement_tree: bool
        """
        reference = await self.sql_uow.references.get_by_pk(
            enhancement.reference_id, preload=["enhancements", "identifiers"]
        )

        if enhancement.derived_from:
            try:
                if enforce_enhancement_tree:
                    parent_enhancements = await self.sql_uow.enhancements.get_by_pks(
                        enhancement.derived_from
                    )

                    invalid_derived_from_ids = [
                        str(parent.id)
                        for parent in parent_enhancements
                        if parent.reference_id != enhancement.reference_id
                    ]

                    if invalid_derived_from_ids:
                        detail = (
                            f"Parent enhancements {",".join(invalid_derived_from_ids)} "
                            "are for a different parent reference"
                        )
                        raise InvalidParentEnhancementError(detail=detail)
                else:
                    await self.sql_uow.enhancements.verify_pk_existence(
                        enhancement.derived_from
                    )

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
        return await self._add_enhancement(enhancement, enforce_enhancement_tree=True)

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
    async def get_reference_from_identifier(
        self, identifier: ExternalIdentifierSearch
    ) -> Reference:
        """Get a single reference by identifier."""
        db_identifier = (
            await self.sql_uow.external_identifiers.get_by_type_and_identifier(
                identifier.identifier_type,
                identifier.identifier,
                identifier.other_identifier_name,
            )
        )
        return await self.sql_uow.references.get_by_pk(
            db_identifier.reference_id, preload=["identifiers", "enhancements"]
        )

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
        self, record_str: str, entry_ref: int, collision_strategy: CollisionStrategy
    ) -> ReferenceCreateResult | None:
        """Ingest a reference from a file."""
        if not settings.feature_flags.deduplication:
            # Back-compatible merging on simple collision and merge strategy
            # Removing this can also remove IngestionService entirely
            (
                validation_result,
                reference,
            ) = await self._ingestion_service.validate_and_collide_reference(
                record_str, entry_ref, collision_strategy
            )
            if reference:
                await self._merge_reference(reference)
            return validation_result

        # Full deduplication flow
        reference_create_result = ReferenceCreateResult.from_raw(record_str, entry_ref)
        if not reference_create_result.reference:
            return reference_create_result
        reference = self._anti_corruption_service.reference_from_sdk_file_input(
            reference_create_result.reference
        )

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
                reference=reference,
                duplicate_determination=DuplicateDetermination.EXACT_DUPLICATE,
                canonical_reference_id=canonical_reference.id,
            )
            return reference_create_result

        duplicate_decision = (
            await self._deduplication_service.register_duplicate_decision_for_reference(
                reference=reference
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

        # Add any extra parameters here!

        return await self.sql_uow.enhancement_requests.add(enhancement_request)

    @sql_unit_of_work
    async def get_enhancement_request(
        self,
        enhancement_request_id: UUID,
    ) -> EnhancementRequest:
        """Get a batch enhancement request by request id."""
        return await self.sql_uow.enhancement_requests.get_by_pk(enhancement_request_id)

    @sql_unit_of_work
    async def collect_and_dispatch_references_for_enhancement(
        self,
        enhancement_request: EnhancementRequest,
        robot_service: RobotService,
        robot_request_dispatcher: RobotRequestDispatcher,
        blob_repository: BlobRepository,
    ) -> None:
        """Collect and dispatch references for batch enhancement."""
        robot = await robot_service.get_robot(enhancement_request.robot_id)
        file_stream = FileStream(
            self._get_jsonl_hydrated_references,
            [
                {
                    "reference_ids": reference_id_chunk,
                }
                for reference_id_chunk in list_chunker(
                    enhancement_request.reference_ids,
                    settings.upload_file_chunk_size_override.get(
                        UploadFile.ENHANCEMENT_REQUEST_REFERENCE_DATA,
                        settings.default_upload_file_chunk_size,
                    ),
                )
            ],
        )

        robot_request = await self._enhancement_service.build_robot_request(
            blob_repository, file_stream, enhancement_request
        )

        try:
            await robot_request_dispatcher.send_enhancement_request_to_robot(
                endpoint="/batch/",
                robot=robot,
                robot_request=robot_request,
            )
        except RobotUnreachableError as exception:
            await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.FAILED,
                error=exception.detail,
            )
        except RobotEnhancementError as exception:
            await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.REJECTED,
                error=exception.detail,
            )
        else:
            await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.ACCEPTED,
            )

    @sql_unit_of_work
    async def validate_and_import_enhancement_result(
        self,
        enhancement_request: EnhancementRequest,
        blob_repository: BlobRepository,
    ) -> tuple[EnhancementRequestStatus, set[UUID]]:
        """
        Validate and import the result of a enhancement request.

        This process:
        - streams the result of the enhancement request line-by-line
        - adds the enhancement to the database
        - streams the validation result to the blob storage service line-by-line
        - does some final validation of missing references and updates the request
        """
        # Mutable set to track imported enhancement IDs
        imported_enhancement_ids: set[UUID] = set()
        validation_result_file = await blob_repository.upload_file_to_blob_storage(
            content=FileStream(
                generator=self._enhancement_service.process_enhancement_result(
                    blob_repository=blob_repository,
                    enhancement_request=enhancement_request,
                    add_enhancement=self.handle_enhancement_result_entry,
                    imported_enhancement_ids=imported_enhancement_ids,
                )
            ),
            path="enhancement_result",
            filename=f"{enhancement_request.id}_repo.jsonl",
        )

        await (
            self._enhancement_service.add_validation_result_file_to_enhancement_request(
                enhancement_request.id, validation_result_file
            )
        )

        # This is a bit hacky - we retrieve the terminal status from the import,
        # and then set to indexing. Essentially using the SQL UOW as a transport
        # from the blob generator to this layer.
        enhancement_request = await self.sql_uow.enhancement_requests.get_by_pk(
            enhancement_request.id
        )
        terminal_status = enhancement_request.request_status

        await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id,
            request_status=EnhancementRequestStatus.INDEXING,
        )
        return terminal_status, imported_enhancement_ids

    async def handle_enhancement_result_entry(
        self,
        enhancement: Enhancement,
    ) -> tuple[bool, str]:
        """Handle the import of a single batch enhancement result entry."""
        try:
            await self._add_enhancement(enhancement, enforce_enhancement_tree=True)
        except SQLNotFoundError:
            return (
                False,
                "Reference does not exist.",
            )
        except Exception:
            logger.exception(
                "Failed to add enhancement to reference.",
                reference_id=enhancement.reference_id,
                enhancement=enhancement,
            )
            return (
                False,
                "Failed to add enhancement to reference.",
            )

        return (
            True,
            "Enhancement added.",
        )

    @sql_unit_of_work
    async def mark_enhancement_request_failed(
        self,
        enhancement_request_id: UUID,
        error: str,
    ) -> EnhancementRequest:
        """Mark a batch enhancement request as failed and supply error message."""
        return await self._enhancement_service.mark_enhancement_request_failed(
            enhancement_request_id, error
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
        canonical_references: list[Reference] = await asyncio.gather(
            *[
                self._get_canonical_reference(enhancement.reference_id)
                for enhancement in enhancements
            ]
        )
        return [
            ReferenceWithChangeset(
                **canonical_reference.model_dump(),
                delta_reference=Reference(
                    id=enhancement.reference_id,
                    enhancements=[enhancement],
                ),
            )
            for enhancement, canonical_reference in zip(
                enhancements, canonical_references, strict=True
            )
        ]

    @es_unit_of_work
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

    @sql_unit_of_work
    @es_unit_of_work
    async def process_reference_duplicate_decision(
        self,
        reference_duplicate_decision: ReferenceDuplicateDecision,
    ) -> tuple[ReferenceDuplicateDecision, bool]:
        """Process a reference duplicate decision."""
        reference_duplicate_decision = (
            await self._deduplication_service.nominate_candidate_duplicates(
                reference_duplicate_decision
            )
        )

        reference_duplicate_decision = (
            await self._deduplication_service.determine_duplicate_from_candidates(
                reference_duplicate_decision
            )
        )

        (
            reference_duplicate_decision,
            decision_changed,
        ) = await self._deduplication_service.map_duplicate_decision(
            reference_duplicate_decision
        )

        if reference_duplicate_decision.active_decision:
            await self._synchronizer.references.sql_to_es(
                reference_duplicate_decision.reference_id
            )

        return reference_duplicate_decision, decision_changed
