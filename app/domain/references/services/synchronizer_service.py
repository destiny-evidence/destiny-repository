"""Service to synchronize Reference models between persistence implementations."""

from uuid import UUID

from opentelemetry.trace import get_tracer

from app.core.telemetry.attributes import Attributes, trace_attribute
from app.domain.references.models.models import Reference
from app.domain.references.models.projections import DeduplicatedReferenceProjection
from app.domain.references.repository import (
    ReferenceESRepository,
    ReferenceSQLRepository,
)

tracer = get_tracer(__name__)


class ReferenceSynchronizer:
    """Service to synchronize Reference models between persistence implementations."""

    def __init__(
        self, sql_repo: ReferenceSQLRepository, es_repo: ReferenceESRepository
    ) -> None:
        """Initialize the service with the required repositories."""
        self.sql_repo = sql_repo
        self.es_repo = es_repo

    @tracer.start_as_current_span("Sync Reference SQL->ES")
    async def sql_to_es(self, reference_id: UUID) -> Reference:
        """Synchronize a reference from SQL to Elasticsearch."""
        trace_attribute(Attributes.DB_PK, str(reference_id))
        reference = await self.sql_repo.get_by_pk(
            reference_id,
            preload=[
                "identifiers",
                "enhancements",
                "canonical_reference",
                "duplicate_references",
                "duplicate_decision",
            ],
        )
        if not reference.canonical_like and reference.canonical_reference:
            # If definitely a duplicate, we don't index and we update the canonical
            await self.es_repo.delete_by_pk(reference.id)
            return await self.sql_to_es(reference.canonical_reference.id)
        return await self.es_repo.add(
            DeduplicatedReferenceProjection.get_from_reference(reference)
        )
