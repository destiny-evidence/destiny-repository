"""Integration tests for what automatic duplicate decisions leave in the database."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import DeduplicationValueError
from app.domain.references import service as reference_service_module
from app.domain.references.models.models import (
    DeduplicationAssessmentPurpose,
    DuplicateDetermination,
    ReferenceDuplicateDecision,
)
from app.domain.references.models.sql import (
    DeduplicationAssessmentRecord as SQLDeduplicationAssessmentRecord,
)
from app.domain.references.models.sql import (
    ReferenceDuplicateDecision as SQLReferenceDuplicateDecision,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_service import (
    ACTING_POLICY_GENERATION,
)
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.integration.deduplication import (
    FakePairScorer,
    add_decision,
    add_reference,
    assessment_count,
    select_candidates,
    stored_decision,
)

settings = get_settings()


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


async def test_an_undecided_assessment_commits_unresolved_and_linked(
    session: AsyncSession, service: ReferenceService, blob_repository: MagicMock
) -> None:
    """Two clearing candidates leave it unresolved, listable by its generation."""
    incoming = await add_reference(session)
    first, second = await add_reference(session), await add_reference(session)
    pending = await add_decision(session, incoming.id, DuplicateDetermination.PENDING)
    for canonical in (first, second):
        await add_decision(session, canonical.id, DuplicateDetermination.CANONICAL)
    await session.commit()
    select_candidates(service, first.id, second.id)

    reproject = await service.process_reference_duplicate_decision(
        pending, blob_repository=blob_repository
    )

    unresolved = await stored_decision(session, pending.id)
    assert unresolved.duplicate_determination == DuplicateDetermination.UNRESOLVED
    assert unresolved.active_decision is False
    assert unresolved.detail == "Unresolved: multiple_clearing"
    assert reproject == []
    by_generation = (
        await session.execute(
            select(SQLReferenceDuplicateDecision.id)
            .join(
                SQLDeduplicationAssessmentRecord,
                SQLDeduplicationAssessmentRecord.idempotency_key
                == SQLReferenceDuplicateDecision.id,
            )
            .where(
                SQLDeduplicationAssessmentRecord.purpose
                == DeduplicationAssessmentPurpose.DEDUPLICATION,
                SQLDeduplicationAssessmentRecord.policy_generation
                == ACTING_POLICY_GENERATION,
            )
        )
    ).scalars()
    assert list(by_generation) == [pending.id]


@pytest.mark.parametrize(
    "match_determination", [None, DuplicateDetermination.UNSEARCHABLE]
)
async def test_a_match_that_is_not_canonical_is_unresolved(
    session: AsyncSession,
    service: ReferenceService,
    blob_repository: MagicMock,
    match_determination: DuplicateDetermination | None,
) -> None:
    """Only a canonical can take duplicates, so any other match is unresolved."""
    incoming = await add_reference(session)
    match = await add_reference(session)
    pending = await add_decision(session, incoming.id, DuplicateDetermination.PENDING)
    if match_determination:
        await add_decision(session, match.id, match_determination)
    await session.commit()
    select_candidates(service, match.id)

    reproject = await service.process_reference_duplicate_decision(
        pending, blob_repository=blob_repository
    )

    unresolved = await stored_decision(session, pending.id)
    assert unresolved.duplicate_determination == DuplicateDetermination.UNRESOLVED
    assert unresolved.detail == "Unresolved: non_canonical_match"
    assert await assessment_count(session, pending.id) == 1
    assert reproject == []


async def test_a_rolled_back_attempt_leaves_nothing_and_its_retry_records_once(
    session: AsyncSession, service: ReferenceService, blob_repository: MagicMock
) -> None:
    """A failure after recording rolls the assessment back; the retry records once."""
    incoming = await add_reference(session)
    canonical = await add_reference(session)
    pending = await add_decision(session, incoming.id, DuplicateDetermination.PENDING)
    await add_decision(session, canonical.id, DuplicateDetermination.CANONICAL)
    await session.commit()
    select_candidates(service, canonical.id)
    deduplication_service = service._deduplication_service  # noqa: SLF001
    map_duplicate_decision = deduplication_service.map_duplicate_decision
    deduplication_service.map_duplicate_decision = AsyncMock(  # type: ignore[method-assign]
        side_effect=DeduplicationValueError("boom")
    )

    with pytest.raises(DeduplicationValueError):
        await service.process_reference_duplicate_decision(
            pending, blob_repository=blob_repository
        )

    assert (await stored_decision(session, pending.id)).duplicate_determination == (
        DuplicateDetermination.PENDING
    )
    assert await assessment_count(session, pending.id) == 0

    deduplication_service.map_duplicate_decision = map_duplicate_decision  # type: ignore[method-assign]
    retry = ReferenceDuplicateDecision.model_validate(
        await stored_decision(session, pending.id), from_attributes=True
    )
    reproject = await service.process_reference_duplicate_decision(
        retry, blob_repository=blob_repository
    )

    decided = await stored_decision(session, pending.id)
    assert decided.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert decided.canonical_reference_id == canonical.id
    assert decided.active_decision is True
    assert await assessment_count(session, pending.id) == 1
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
    reference = await add_reference(session)
    decision = await add_decision(session, reference.id, determination)
    await session.commit()

    await service.mark_duplicate_decision_unsearchable(decision.id, detail="spent")

    stored = await stored_decision(session, decision.id)
    assert stored.duplicate_determination == expected
    assert stored.active_decision is True
