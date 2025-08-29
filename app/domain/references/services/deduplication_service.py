"""Service for managing reference duplicate detection."""

import uuid

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    DuplicateDetermination,
    IngestionProcess,
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

    async def register_reference(
        self, reference: Reference, source: IngestionProcess, source_id: uuid.UUID
    ) -> ReferenceDuplicateDecision:
        """Register a reference for pending deduplication detection."""
        fingerprint = FingerprintProjection.get_from_reference(reference)
        reference_duplicate_decision = ReferenceDuplicateDecision(
            reference_id=reference.id,
            fingerprint=fingerprint,
            source=source,
            source_id=source_id,
            # We can make preliminary determinations based on definite
            # duplicates (DUPLICATE) or missing data (BLURRED_FINGERPRINT).
            duplicate_determination=DuplicateDetermination.BLURRED_FINGERPRINT
            if fingerprint.searchable
            else DuplicateDetermination.PENDING,
        )
        return await self.sql_uow.reference_duplicate_decisions.add(
            reference_duplicate_decision
        )

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
