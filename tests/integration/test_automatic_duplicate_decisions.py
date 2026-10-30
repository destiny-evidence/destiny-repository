"""
Integration tests for automatic duplicate decisions against a real session.

Covers what mocks cannot: what is left in the database once a decision commits
or rolls back, and that a retried attempt records its assessment only once.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import DeduplicationValueError
from app.domain.references import service as reference_service_module
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
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    ReferenceFactory,
)

settings = get_settings()


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


@pytest.fixture
def service(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> ReferenceService:
    """Build a service on the real session with automatic decisions on."""
    monkeypatch.setattr(
        settings.feature_flags, "enable_automatic_deduplication_decisions", True
    )
    monkeypatch.setattr(settings, "trusted_unique_identifier_types", set())
    monkeypatch.setattr(reference_service_module, "DeduperPairScorer", FakePairScorer)
    service = ReferenceService(
        ReferenceAntiCorruptionService(sign_url=AsyncMock()),
        AsyncSqlUnitOfWork(session),
        AsyncESUnitOfWork(AsyncMock()),
    )
    # Percolation needs Elasticsearch, and robot dispatch is not under test here.
    service._detect_and_dispatch_robot_automations = AsyncMock()  # type: ignore[method-assign]  # noqa: SLF001
    return service


@pytest.fixture
def blob_repository() -> MagicMock:
    """Stand in for the payload store, which these tests do not inspect."""
    blob_repository = MagicMock()
    blob_repository.upload_file_to_blob_storage = AsyncMock(
        return_value=MagicMock(to_uri=MagicMock(return_value="azure://payload"))
    )
    return blob_repository


async def _reference(session: AsyncSession) -> Reference:
    reference = ReferenceFactory.build(
        visibility="public",
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="A shared title"
                )
            )
        ],
    )
    for enhancement in reference.enhancements or []:
        enhancement.reference_id = reference.id
    for identifier in reference.identifiers or []:
        identifier.reference_id = reference.id
    return await ReferenceSQLRepository(session).merge(reference)


async def _decide(
    session: AsyncSession, reference_id: UUID, determination: DuplicateDetermination
) -> ReferenceDuplicateDecision:
    return await ReferenceDuplicateDecisionSQLRepository(session).add(
        ReferenceDuplicateDecision(
            reference_id=reference_id,
            decision_authority=DuplicateDecisionAuthority.SYSTEM,
            decision_trigger=DuplicateDecisionTrigger.IMPORT,
            duplicate_determination=determination,
            active_decision=determination != DuplicateDetermination.PENDING,
        )
    )


def _select(service: ReferenceService, *candidate_ids: UUID) -> None:
    """Have retrieval surface exactly these candidates."""
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


async def _stored_decision(session: AsyncSession, decision_id: UUID):  # noqa: ANN202
    session.expire_all()
    return (
        await session.execute(
            select(SQLReferenceDuplicateDecision).where(
                SQLReferenceDuplicateDecision.id == decision_id
            )
        )
    ).scalar_one()


async def _assessment_count(session: AsyncSession, reference_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count()).where(
                SQLDeduplicationAssessmentRecord.incoming_reference_id == reference_id
            )
        )
    ).scalar_one()


async def test_an_undecided_assessment_commits_unresolved_and_linked(
    session: AsyncSession, service: ReferenceService, blob_repository: MagicMock
) -> None:
    """Two clearing candidates leave it unresolved, listable by its generation."""
    incoming = await _reference(session)
    first, second = await _reference(session), await _reference(session)
    pending = await _decide(session, incoming.id, DuplicateDetermination.PENDING)
    for canonical in (first, second):
        await _decide(session, canonical.id, DuplicateDetermination.CANONICAL)
    await session.commit()
    _select(service, first.id, second.id)

    reproject = await service.process_reference_duplicate_decision(
        pending, blob_repository=blob_repository
    )

    unresolved = await _stored_decision(session, pending.id)
    assert unresolved.duplicate_determination == DuplicateDetermination.UNRESOLVED
    assert unresolved.active_decision is False
    assert unresolved.detail == "Unresolved: multiple_clearing"
    assert reproject == []
    by_generation = (
        await session.execute(
            select(SQLReferenceDuplicateDecision.id)
            .join(
                SQLDeduplicationAssessmentRecord,
                SQLDeduplicationAssessmentRecord.id
                == SQLReferenceDuplicateDecision.deduplication_assessment_id,
            )
            .where(
                SQLDeduplicationAssessmentRecord.policy_generation
                == settings.dedup_assessment_recording.policy_generation
            )
        )
    ).scalars()
    assert list(by_generation) == [pending.id]


async def test_a_match_no_longer_canonical_is_unresolved_and_linked(
    session: AsyncSession, service: ReferenceService, blob_repository: MagicMock
) -> None:
    """A clearing candidate that cannot take duplicates is not mapped onto."""
    incoming = await _reference(session)
    stale = await _reference(session)
    pending = await _decide(session, incoming.id, DuplicateDetermination.PENDING)
    await session.commit()
    _select(service, stale.id)

    reproject = await service.process_reference_duplicate_decision(
        pending, blob_repository=blob_repository
    )

    unresolved = await _stored_decision(session, pending.id)
    assert unresolved.duplicate_determination == DuplicateDetermination.UNRESOLVED
    assert unresolved.detail == "Unresolved: non_canonical_match"
    assert unresolved.deduplication_assessment_id is not None
    assert reproject == []


async def test_a_rolled_back_attempt_leaves_nothing_and_its_retry_records_once(
    session: AsyncSession, service: ReferenceService, blob_repository: MagicMock
) -> None:
    """A failure after recording rolls the assessment back; the retry lands."""
    incoming = await _reference(session)
    canonical = await _reference(session)
    pending = await _decide(session, incoming.id, DuplicateDetermination.PENDING)
    await _decide(session, canonical.id, DuplicateDetermination.CANONICAL)
    await session.commit()
    _select(service, canonical.id)
    deduplication_service = service._deduplication_service  # noqa: SLF001
    map_duplicate_decision = deduplication_service.map_duplicate_decision
    deduplication_service.map_duplicate_decision = AsyncMock(  # type: ignore[method-assign]
        side_effect=DeduplicationValueError("boom")
    )

    with pytest.raises(DeduplicationValueError):
        await service.process_reference_duplicate_decision(
            pending, blob_repository=blob_repository
        )

    assert (await _stored_decision(session, pending.id)).duplicate_determination == (
        DuplicateDetermination.PENDING
    )
    assert await _assessment_count(session, incoming.id) == 0

    deduplication_service.map_duplicate_decision = map_duplicate_decision  # type: ignore[method-assign]
    retry = ReferenceDuplicateDecision.model_validate(
        await _stored_decision(session, pending.id), from_attributes=True
    )
    reproject = await service.process_reference_duplicate_decision(
        retry, blob_repository=blob_repository
    )

    decided = await _stored_decision(session, pending.id)
    assert decided.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert decided.canonical_reference_id == canonical.id
    assert decided.active_decision is True
    assert decided.deduplication_assessment_id is not None
    assert await _assessment_count(session, incoming.id) == 1
    assert reproject == [incoming.id]


@pytest.mark.parametrize(
    ("determination", "expected"),
    [
        (DuplicateDetermination.PENDING, DuplicateDetermination.UNSEARCHABLE),
        (DuplicateDetermination.CANONICAL, DuplicateDetermination.CANONICAL),
    ],
)
async def test_exhausted_attempts_only_decide_a_pending_decision(
    session: AsyncSession,
    service: ReferenceService,
    determination: DuplicateDetermination,
    expected: DuplicateDetermination,
) -> None:
    """A decision another worker already made is never overwritten."""
    reference = await _reference(session)
    decision = await _decide(session, reference.id, determination)
    await session.commit()

    await service.mark_duplicate_decision_unsearchable(decision.id, detail="spent")

    stored = await _stored_decision(session, decision.id)
    assert stored.duplicate_determination == expected
    assert stored.active_decision is True
