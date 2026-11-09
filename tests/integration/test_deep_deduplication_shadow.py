"""
Integration tests for the deep deduplication shadow against a real session.

Covers what mocks cannot: a genuine SQL error reaches the caller rather than being
absorbed and leaves the session usable, and the decision that runs after the shadow
is the one the trusted identifier shortcut makes on its own.
"""

from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.references import service as reference_service_module
from app.domain.references.models.models import (
    CandidateSelectionRequest,
    DeduplicationAssessmentPurpose,
    DuplicateDetermination,
    ExternalIdentifierType,
    Reference,
    ReferenceDuplicateDecision,
)
from app.domain.references.models.sql import (
    DeduplicationAssessmentRecord as SQLDeduplicationAssessmentRecord,
)
from app.domain.references.models.sql import (
    ExternalIdentifier as SQLExternalIdentifier,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import LinkedExternalIdentifierFactory, OpenAlexIdentifierFactory
from tests.integration.deduplication import (
    FakePairScorer,
    add_decision,
    add_reference,
    select_candidates,
    stored_decision,
)

settings = get_settings()


@pytest.fixture
def service(session: AsyncSession) -> ReferenceService:
    """Build a service on the real session; Elasticsearch is never reached."""
    service = ReferenceService(
        ReferenceAntiCorruptionService(sign_url=AsyncMock()),
        AsyncSqlUnitOfWork(session),
        AsyncESUnitOfWork(AsyncMock()),
    )
    # Percolation needs Elasticsearch, and robot dispatch is not under test here.
    service._detect_and_dispatch_robot_automations = AsyncMock()  # type: ignore[method-assign]  # noqa: SLF001
    return service


async def test_a_sql_failure_in_the_shadow_reaches_the_caller(
    session: AsyncSession,
    service: ReferenceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller sees the failure, and the write that runs next still commits."""
    reference = await add_reference(session)
    await session.commit()

    async def _fail_against_the_database(
        _request: CandidateSelectionRequest, **_kwargs: object
    ) -> None:
        await service.sql_uow.session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(
        service._deduplication_service,  # noqa: SLF001
        "get_deduplication_candidates",
        _fail_against_the_database,
    )

    with pytest.raises(DBAPIError):
        await service.run_deep_deduplication_shadow(
            ReferenceDuplicateDecision(
                reference_id=reference.id,
                duplicate_determination=DuplicateDetermination.PENDING,
            ),
            blob_repository=AsyncMock(),
        )

    identifier = await service.add_identifier(
        reference.id, OpenAlexIdentifierFactory.build()
    )

    session.expire_all()
    persisted = await session.execute(
        select(SQLExternalIdentifier).where(SQLExternalIdentifier.id == identifier.id)
    )
    assert persisted.scalar_one_or_none() is not None


class ShortcutCase(NamedTuple):
    """A pending reference whose OpenAlex ID matches a held one."""

    held: Reference
    other: Reference
    pending: ReferenceDuplicateDecision


@pytest.fixture
async def shortcut_case(
    session: AsyncSession, service: ReferenceService, monkeypatch: pytest.MonkeyPatch
) -> ShortcutCase:
    """Store a reference the shortcut matches to a held one, and offer another."""
    monkeypatch.setattr(
        settings, "trusted_unique_identifier_types", {ExternalIdentifierType.OPEN_ALEX}
    )
    monkeypatch.setattr(reference_service_module, "DeduperPairScorer", FakePairScorer)
    openalex_id = OpenAlexIdentifierFactory.build()
    held, incoming = [
        await add_reference(
            session,
            identifiers=[LinkedExternalIdentifierFactory.build(identifier=openalex_id)],
        )
        for _ in range(2)
    ]
    other = await add_reference(session)
    for canonical in (held, other):
        await add_decision(session, canonical.id, DuplicateDetermination.CANONICAL)
    pending = await add_decision(session, incoming.id, DuplicateDetermination.PENDING)
    await session.commit()
    select_candidates(service, other.id)
    return ShortcutCase(held=held, other=other, pending=pending)


async def shadow_record(
    session: AsyncSession, decision_id: UUID
) -> SQLDeduplicationAssessmentRecord | None:
    """Read the shadow's record for a decision, if it wrote one."""
    return (
        await session.execute(
            select(SQLDeduplicationAssessmentRecord).where(
                SQLDeduplicationAssessmentRecord.idempotency_key == decision_id,
                SQLDeduplicationAssessmentRecord.purpose
                == DeduplicationAssessmentPurpose.PERFORMANCE_SHADOW,
            )
        )
    ).scalar_one_or_none()


async def test_the_shortcut_decides_alone_after_a_shadow_proposes_another_match(
    session: AsyncSession,
    service: ReferenceService,
    blob_repository: MagicMock,
    shortcut_case: ShortcutCase,
) -> None:
    """The shadow records its proposal and writes no decision."""
    await service.run_deep_deduplication_shadow(
        shortcut_case.pending, blob_repository=blob_repository
    )

    shadowed = await stored_decision(session, shortcut_case.pending.id)
    assert shadowed.duplicate_determination == DuplicateDetermination.PENDING
    record = await shadow_record(session, shortcut_case.pending.id)
    assert record is not None
    assert record.proposed_duplicate_of_id == shortcut_case.other.id

    await service.process_reference_duplicate_decision(
        shortcut_case.pending, blob_repository=blob_repository
    )

    decided = await stored_decision(session, shortcut_case.pending.id)
    assert decided.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert decided.canonical_reference_id == shortcut_case.held.id
    assert decided.active_decision is True


async def test_the_shortcut_decides_alone_after_a_shadow_fails(
    session: AsyncSession,
    service: ReferenceService,
    blob_repository: MagicMock,
    shortcut_case: ShortcutCase,
) -> None:
    """A failed shadow records nothing and writes no decision."""
    service._deduplication_service.get_deduplication_candidates = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        side_effect=RuntimeError("search failed")
    )

    with pytest.raises(RuntimeError):
        await service.run_deep_deduplication_shadow(
            shortcut_case.pending, blob_repository=blob_repository
        )

    shadowed = await stored_decision(session, shortcut_case.pending.id)
    assert shadowed.duplicate_determination == DuplicateDetermination.PENDING
    assert await shadow_record(session, shortcut_case.pending.id) is None

    await service.process_reference_duplicate_decision(
        shortcut_case.pending, blob_repository=blob_repository
    )

    decided = await stored_decision(session, shortcut_case.pending.id)
    assert decided.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert decided.canonical_reference_id == shortcut_case.held.id
    assert decided.active_decision is True
