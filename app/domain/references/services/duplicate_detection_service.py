"""Service for managing reference duplicate detection."""

import uuid

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    DuplicateDetermination,
    Process,
    Reference,
    ReferenceDuplicateDecision,
)
from app.domain.references.models.projections import FingerprintProjection
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class DuplicateDetectionService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing reference duplicate detection."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    async def register_candidate_reference(
        self, reference: Reference, source: Process, source_id: uuid.UUID
    ) -> ReferenceDuplicateDecision:
        """Register a reference for pending deduplication detection."""
        fingerprint = FingerprintProjection.get_from_reference(reference)
        reference_duplicate_decision = ReferenceDuplicateDecision(
            reference_id=reference.id,
            fingerprint=fingerprint,
            source=source,
            source_id=source_id,
            # We can make preliminary determinations based on definite
            # duplicates (DUPLICATE) or missing data (UNRESOLVABLE).
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        return await self.sql_uow.reference_duplicate_decisions.add(
            reference_duplicate_decision
        )
