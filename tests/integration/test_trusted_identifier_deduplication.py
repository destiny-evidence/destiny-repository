"""
Integration test for trusted identifier shortcut deduplication.

Verifies that when two references share a trusted identifier and both have
pending duplicate decisions, processing them sequentially results in one
canonical and one duplicate — even when the second decision is processed after
the first has already created a side-effect decision for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tenacity import retry, stop_after_attempt, wait_fixed

from app.core.config import get_settings
from app.domain.references.models.models import (
    DuplicateDetermination,
    ExternalIdentifierType,
)
from app.domain.references.models.sql import (
    ReferenceDuplicateDecision as SQLReferenceDuplicateDecision,
)
from app.domain.references.repository import (
    ReferenceESRepository,
    ReferenceSQLRepository,
)
from app.main import app
from tests.e2e.utils import TestPollingExhaustedError
from tests.factories import (
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    ReferenceFactory,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from elasticsearch import AsyncElasticsearch
    from sqlalchemy.ext.asyncio import AsyncSession

settings = get_settings()

pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
async def client(app: FastAPI = app) -> AsyncIterator[AsyncClient]:
    """Create a test client for the FastAPI application."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer foo"},
    ) as client:
        yield client


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1), reraise=True)
async def poll_duplicate_process(
    session: AsyncSession,
    reference_id: UUID,
) -> SQLReferenceDuplicateDecision:
    """Poll until most recently created duplicate decision reaches terminal state."""
    session.expire_all()
    query = (
        select(SQLReferenceDuplicateDecision)
        .where(SQLReferenceDuplicateDecision.reference_id == reference_id)
        .order_by(SQLReferenceDuplicateDecision.created_at.desc())
        .limit(1)
    )
    result = await session.execute(query)
    decision = result.scalar_one_or_none()
    if decision is None:
        msg = "No duplicate decision found for reference"
        raise TestPollingExhaustedError(msg)

    terminal_states = DuplicateDetermination.get_terminal_states()
    if decision.duplicate_determination not in terminal_states:
        msg = "Most recent duplicate decision not yet in a terminal state"
        raise TestPollingExhaustedError(msg)

    return decision


async def test_shortcut_deduplication_both_pending_decisions(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    es_client: AsyncElasticsearch,
) -> None:
    """
    Two references with the same trusted identifier and pending decisions.

    Processing the first reference's decision should mark it canonical and
    create a side-effect duplicate decision for the second. Processing the
    second reference's original pending decision should then recognise that
    the first is already canonical and mark the second as duplicate.
    """
    # -- Enable trusted identifier shortcutting ---
    monkeypatch.setattr(
        settings,
        "trusted_unique_identifier_types",
        {ExternalIdentifierType.OPEN_ALEX},
    )

    # Create two references with a shared openalex identifier
    shared_openalex_id = "W1234567890"

    reference_1 = ReferenceFactory.build(
        identifiers=[
            LinkedExternalIdentifierFactory.build(
                identifier=OpenAlexIdentifierFactory.build(
                    identifier=shared_openalex_id
                )
            )
        ]
    )

    reference_2 = ReferenceFactory.build(
        identifiers=[
            LinkedExternalIdentifierFactory.build(
                identifier=OpenAlexIdentifierFactory.build(
                    identifier=shared_openalex_id
                )
            )
        ]
    )

    es_repository = ReferenceESRepository(es_client)
    sql_repository = ReferenceSQLRepository(session)
    for reference in [reference_1, reference_2]:
        await es_repository.add(reference)
        await sql_repository.merge(reference)
    await session.commit()
    await es_client.indices.refresh(index="reference")

    # Invoke deduplication first reference
    invoke_response = await client.post(
        "/v1/references/duplicate-decisions/invoke/",
        json={
            "reference_ids": [
                str(reference_1.id),
            ]
        },
    )

    assert invoke_response.status_code == status.HTTP_202_ACCEPTED

    await poll_duplicate_process(session, reference_id=reference_1.id)

    session.expire_all()

    result = await session.execute(
        select(SQLReferenceDuplicateDecision).where(
            SQLReferenceDuplicateDecision.reference_id == reference_1.id,
            SQLReferenceDuplicateDecision.active_decision.is_(True),
        )
    )
    active_decision_1 = result.scalar_one()
    assert active_decision_1.duplicate_determination == DuplicateDetermination.CANONICAL

    result = await session.execute(
        select(SQLReferenceDuplicateDecision).where(
            SQLReferenceDuplicateDecision.reference_id == reference_2.id,
            SQLReferenceDuplicateDecision.active_decision.is_(True),
        )
    )
    active_decision_2 = result.scalar_one()
    assert active_decision_2.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert active_decision_2.canonical_reference_id == reference_1.id

    # Invoke deduplication for the second reference
    # We don't want this to change duplicate status
    invoke_response = await client.post(
        "/v1/references/duplicate-decisions/invoke/",
        json={
            "reference_ids": [
                str(reference_2.id),
            ]
        },
    )

    assert invoke_response.status_code == status.HTTP_202_ACCEPTED

    await poll_duplicate_process(session, reference_id=reference_2.id)

    session.expire_all()
    result = await session.execute(
        select(SQLReferenceDuplicateDecision).where(
            SQLReferenceDuplicateDecision.reference_id == reference_2.id,
            SQLReferenceDuplicateDecision.active_decision.is_(True),
        )
    )
    active_decision_2 = result.scalar_one()
    assert active_decision_2.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert active_decision_2.canonical_reference_id == reference_1.id
