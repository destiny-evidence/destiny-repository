"""Unit tests for SQL repository functionality."""

from uuid import uuid7

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLNotFoundError
from tests.persistence_models import SimpleDomainModel, SimpleSQLRepository


@pytest.fixture
def repository(session: AsyncSession) -> SimpleSQLRepository:
    return SimpleSQLRepository(session)


async def create_simple_record(
    repository: SimpleSQLRepository,
    **overrides: object,
) -> SimpleDomainModel:
    """Create and persist a simple domain model, returning it."""
    doc = SimpleDomainModel(**overrides)
    await repository.add(doc)
    return doc


async def test_get_by_pks_with_duplicate_ids(
    repository: SimpleSQLRepository,
) -> None:
    """Passing the same ID twice should not raise NotFoundError."""
    record = await create_simple_record(repository, title="duplicate test")

    results = await repository.get_by_pks([record.id, record.id])

    assert len(results) == 1
    assert results[0].id == record.id


async def test_get_by_pks_raises_on_missing(
    repository: SimpleSQLRepository,
) -> None:
    """Should raise SQLNotFoundError when a PK doesn't exist."""
    record = await create_simple_record(repository, title="exists")
    missing_id = uuid7()

    with pytest.raises(SQLNotFoundError, match=str(missing_id)):
        await repository.get_by_pks([record.id, missing_id])
