"""Shared scaffolding for deduplication integration tests."""

from unittest.mock import AsyncMock
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import (
    Candidate,
    CandidateSelectionDiagnostics,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationPairResult,
    DuplicateDecisionAuthority,
    DuplicateDecisionTrigger,
    DuplicateDetermination,
    InputSearchability,
    LinkedExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
    RetrievalPolicyName,
)
from app.domain.references.models.sql import (
    DeduplicationAssessmentRecord as SQLDeduplicationAssessmentRecord,
)
from app.domain.references.models.sql import (
    ReferenceDuplicateDecision as SQLReferenceDuplicateDecision,
)
from app.domain.references.repository import (
    ReferenceDuplicateDecisionSQLRepository,
    ReferenceSQLRepository,
)
from app.domain.references.service import ReferenceService
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    ReferenceFactory,
)


class FakePairScorer:
    """Score every pair as a clear match."""

    metadata = DeduperMetadata(
        package_version="0", configuration_hash="x", threshold=0.5
    )

    async def score_pair(
        self,
        incoming: object,  # noqa: ARG002
        candidate: object,  # noqa: ARG002
    ) -> DeduplicationPairResult:
        """Return a probability that clears any threshold."""
        return DeduplicationPairResult(probability=0.99)


async def add_reference(
    session: AsyncSession,
    identifiers: list[LinkedExternalIdentifier] | None = None,
) -> Reference:
    """Store a reference with a title the scorer can compare."""
    reference = ReferenceFactory.build(
        visibility="public",
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="A shared title"
                )
            )
        ],
        identifiers=identifiers,
    )
    for enhancement in reference.enhancements or []:
        enhancement.reference_id = reference.id
    for identifier in reference.identifiers or []:
        identifier.reference_id = reference.id
    return await ReferenceSQLRepository(session).merge(reference)


async def add_decision(
    session: AsyncSession, reference_id: UUID, determination: DuplicateDetermination
) -> ReferenceDuplicateDecision:
    """Store a system decision from an import, active unless still pending."""
    return await ReferenceDuplicateDecisionSQLRepository(session).add(
        ReferenceDuplicateDecision(
            reference_id=reference_id,
            decision_authority=DuplicateDecisionAuthority.SYSTEM,
            decision_trigger=DuplicateDecisionTrigger.IMPORT,
            duplicate_determination=determination,
            active_decision=determination != DuplicateDetermination.PENDING,
        )
    )


def select_candidates(service: ReferenceService, *candidate_ids: UUID) -> None:
    """Make retrieval return exactly these candidates."""
    service._deduplication_service.get_deduplication_candidates = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        return_value=CandidateSelectionResult(
            retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V2,
            k_requested=10,
            input_searchability=InputSearchability(searchable=True, reason="ok"),
            diagnostics=CandidateSelectionDiagnostics(
                candidate_count=len(candidate_ids)
            ),
            candidates=[
                Candidate(reference_id=candidate_id, rank=rank, routes=[])
                for rank, candidate_id in enumerate(candidate_ids, start=1)
            ],
        )
    )


async def stored_decision(
    session: AsyncSession, decision_id: UUID
) -> SQLReferenceDuplicateDecision:
    """Read a decision as committed, past the session's identity map."""
    session.expire_all()
    return (
        await session.execute(
            select(SQLReferenceDuplicateDecision).where(
                SQLReferenceDuplicateDecision.id == decision_id
            )
        )
    ).scalar_one()


async def assessment_count(session: AsyncSession, decision_id: UUID) -> int:
    """Count the assessments keyed by a decision's id."""
    return (
        await session.execute(
            select(func.count()).where(
                SQLDeduplicationAssessmentRecord.idempotency_key == decision_id
            )
        )
    ).scalar_one()
