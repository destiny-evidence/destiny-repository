"""Service for managing reference duplicate detection."""

import uuid
from typing import Literal

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.models import (
    DuplicateDetermination,
    ExternalIdentifierType,
    GenericExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
)
from app.domain.references.models.projections import (
    CandidacyFingerprintProjection,
    FingerprintProjection,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class DeduplicationService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing reference duplicate detection."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    async def find_exact_duplicate(self, reference: Reference) -> Reference | None:
        """
        Find exact duplicate references for the given reference.

        This is _not_ part of the regular deduplication flow but is used to circumvent
        importing and processing redundant references.

        Exact duplicates are defined in ``Reference.is_superset()``. A reference may
        have more than one exact duplicate, this just returns the first.
        """
        if not reference.identifiers:
            msg = "Reference must have identifiers to find duplicates."
            raise ValueError(msg)

        # We can't be sure of low cardinality on "other" identifiers, so make sure
        # there's at least one defined identifier type.
        if not any(
            identifier.identifier.identifier_type != ExternalIdentifierType.OTHER
            for identifier in reference.identifiers
        ):
            logger.warning(
                "Reference did not have any non-other identifiers, exact duplicate "
                "search skipped."
            )
            return None

        # First, find candidates. These are the references with all identical
        # identifiers to the given reference.
        candidates = await self.sql_uow.references.find_with_identifiers(
            [
                GenericExternalIdentifier.from_specific(identifier.identifier)
                for identifier in reference.identifiers
            ],
            preload=["identifiers", "enhancements", "duplicate_decision"],
        )

        # Now, find if any candidates are perfect supersets of the new reference.
        # Try canonical references first to form a nicer tree, but it's
        # not super important.
        for candidate in sorted(
            candidates,
            key=lambda candidate: (
                1
                if candidate.canonical is True
                else 0
                if candidate.canonical is False
                else -1
            ),
            reverse=True,
        ):
            if candidate.is_superset(reference):
                return candidate
        return None

    async def dispatch_deduplication_for_reference(
        self,
        reference: Reference,
        # Used for passing down exact duplicates
        duplicate_determination: Literal[DuplicateDetermination.EXACT_DUPLICATE]
        | None = None,
        canonical_reference_id: uuid.UUID | None = None,
    ) -> ReferenceDuplicateDecision:
        """Register a reference for pending deduplication detection."""
        fingerprint = FingerprintProjection.get_from_reference(reference)
        reference_duplicate_decision = ReferenceDuplicateDecision(
            reference_id=reference.id,
            fingerprint=fingerprint,
            duplicate_determination=(
                duplicate_determination
                if duplicate_determination
                else (
                    DuplicateDetermination.BLURRED_FINGERPRINT
                    if not fingerprint.searchable
                    else DuplicateDetermination.PENDING
                )
            ),
            canonical_reference_id=canonical_reference_id,
        )
        reference_duplicate_decision = (
            await self.sql_uow.reference_duplicate_decisions.add(
                reference_duplicate_decision
            )
        )
        await queue_task_with_trace(
            "app.domain.references.tasks.process_reference_duplicate_decision",
            reference_duplicate_decision.id,
        )
        return reference_duplicate_decision

    async def nominate_candidate_duplicates(
        self, reference_duplicate_decisions: list[ReferenceDuplicateDecision]
    ) -> list[ReferenceDuplicateDecision]:
        """Get candidate duplicate references for the given decisions."""
        search_results = await self.es_uow.references.search_fingerprints(
            [
                CandidacyFingerprintProjection.get_from_fingerprint(
                    decision.fingerprint
                )
                for decision in reference_duplicate_decisions
            ]
        )

        for reference_duplicate_decision, search_result in zip(
            reference_duplicate_decisions, search_results, strict=True
        ):
            if not search_result:
                reference_duplicate_decision.duplicate_determination = (
                    DuplicateDetermination.CANONICAL
                )
                self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    duplicate_determination=DuplicateDetermination.CANONICAL,
                )
            else:
                # Is there a search result score that would be enough for us to mark as
                # duplicate?
                reference_duplicate_decision.duplicate_determination = (
                    DuplicateDetermination.NOMINATED
                )
                reference_duplicate_decision.candidate_duplicate_ids = [
                    res.id for res in search_result.candidate_duplicates
                ]
                self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    candidate_duplicate_ids=reference_duplicate_decision.candidate_duplicate_ids,
                    duplicate_determination=reference_duplicate_decision.duplicate_determination,
                )

        return reference_duplicate_decisions

    async def detect_duplicates(self) -> list[uuid.UUID]:
        """Detect duplicate references based on given candidate fingerprints."""
        return []
