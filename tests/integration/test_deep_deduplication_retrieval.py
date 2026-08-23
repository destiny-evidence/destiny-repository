"""
Integration test for deep deduplication retrieval against a real session.

Covers what a mocked failure cannot: a genuine SQL error reaches the caller
rather than being absorbed, and leaves the session usable for the decision that
runs next. A mocked TimeoutError never touches the session and proves neither.
"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.sql import (
    ExternalIdentifier as SQLExternalIdentifier,
)
from app.domain.references.repository import ReferenceSQLRepository
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import OpenAlexIdentifierFactory, ReferenceFactory


@pytest.fixture
def service(session: AsyncSession) -> ReferenceService:
    """Build a service on the real session; Elasticsearch is never reached."""
    return ReferenceService(
        ReferenceAntiCorruptionService(sign_url=AsyncMock()),
        AsyncSqlUnitOfWork(session),
        AsyncESUnitOfWork(AsyncMock()),
    )


async def test_a_sql_failure_in_retrieval_reaches_the_caller(
    session: AsyncSession,
    service: ReferenceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller sees the failure, and the write that runs next still commits."""
    reference = await ReferenceSQLRepository(session).add(ReferenceFactory.build())
    await session.commit()

    async def _fail_against_the_database(_reference_id: UUID) -> None:
        await service.sql_uow.session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(
        service._deduplication_service,  # noqa: SLF001
        "select_candidate_canonicals",
        _fail_against_the_database,
    )

    with pytest.raises(DBAPIError):
        await service.run_deep_deduplication_retrieval(reference.id)

    identifier = await service.add_identifier(
        reference.id, OpenAlexIdentifierFactory.build()
    )

    session.expire_all()
    persisted = await session.execute(
        select(SQLExternalIdentifier).where(SQLExternalIdentifier.id == identifier.id)
    )
    assert persisted.scalar_one_or_none() is not None
