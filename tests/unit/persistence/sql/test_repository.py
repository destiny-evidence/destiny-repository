"""Unit tests for SQL repository functionality."""

from unittest.mock import AsyncMock, patch
from uuid import uuid7

import pytest
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLNotFoundError
from app.persistence.sql.repository import (
    BIND_PARAM_FORK_THRESHOLD,
    GenericAsyncSqlRepository,
)
from tests.persistence_models import (
    SimpleDomainModel,
    SimpleSQLModel,
    SimpleSQLRepository,
)


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


async def test_wait_for_pk_returns_existing_record(
    repository: SimpleSQLRepository,
) -> None:
    """Should return the record immediately if it already exists."""
    record = await create_simple_record(repository, title="exists")

    result = await repository.wait_for_pk(record.id)

    assert result.id == record.id


async def test_wait_for_pk_retries_until_record_appears(
    repository: SimpleSQLRepository,
) -> None:
    """Should retry and return the record once it becomes available."""
    record = SimpleDomainModel(title="delayed")
    with patch.object(repository, "_get_by_pk", AsyncMock(side_effect=[None, record])):
        result = await repository.wait_for_pk(record.id, timeout=1, interval=0.05)

    assert result.id == record.id


async def test_wait_for_pk_raises_after_timeout(
    repository: SimpleSQLRepository,
) -> None:
    """Should raise SQLNotFoundError if the record never appears within the timeout."""
    missing_id = uuid7()

    with pytest.raises(SQLNotFoundError):
        await repository.wait_for_pk(missing_id, timeout=0.1, interval=0.05)


async def test_get_by_pks_raises_on_missing(
    repository: SimpleSQLRepository,
) -> None:
    """Should raise SQLNotFoundError when a PK doesn't exist."""
    record = await create_simple_record(repository, title="exists")
    missing_id = uuid7()

    with pytest.raises(SQLNotFoundError, match=str(missing_id)):
        await repository.get_by_pks([record.id, missing_id])


@pytest.mark.parametrize(
    ("n_values", "expect_array"),
    [
        (1, False),
        (BIND_PARAM_FORK_THRESHOLD, False),
        (BIND_PARAM_FORK_THRESHOLD + 1, True),
    ],
)
def test_any_of_forks_on_collection_size(n_values, expect_array):
    """any_of binds one parameter per value until doing so would exceed the limit."""
    values = [uuid7() for _ in range(n_values)]
    compiled = GenericAsyncSqlRepository.any_of(SimpleSQLModel.id, values).compile(
        dialect=PGDialect_asyncpg(), compile_kwargs={"render_postcompile": True}
    )

    if expect_array:
        assert "= ANY" in str(compiled)
        assert len(compiled.params) == 1
    else:
        assert "IN" in str(compiled)
        assert len(compiled.params) == n_values


def test_any_of_empty_collection_matches_nothing():
    """An empty collection compiles to an always-false predicate."""
    compiled = GenericAsyncSqlRepository.any_of(SimpleSQLModel.id, []).compile(
        dialect=PGDialect_asyncpg(), compile_kwargs={"render_postcompile": True}
    )
    assert "1 != 1" in str(compiled)
