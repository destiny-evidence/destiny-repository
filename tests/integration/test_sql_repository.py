"""Tests for GenericAsyncSqlRepository methods."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.persistence_models import SimpleSQLModel, SimpleSQLRepository


@pytest.fixture
def repository(session: AsyncSession) -> SimpleSQLRepository:
    """Create a simple repository for testing."""
    return SimpleSQLRepository(session)


async def test_get_all_pks_empty(repository: SimpleSQLRepository) -> None:
    """Test get_all_pks returns empty list when no records exist."""
    pks = await repository.get_all_pks()
    assert pks == []


async def test_get_all_pks_returns_all(
    repository: SimpleSQLRepository, session: AsyncSession
) -> None:
    """Test get_all_pks returns all primary keys."""
    records = [SimpleSQLModel(title=f"test_{i}") for i in range(5)]
    session.add_all(records)
    await session.commit()

    pks = await repository.get_all_pks()
    assert len(pks) == 5
    assert set(pks) == {r.id for r in records}


async def test_get_all_pks_with_bounds(
    repository: SimpleSQLRepository, session: AsyncSession
) -> None:
    """Test get_all_pks respects min_id and max_id bounds."""
    records = [SimpleSQLModel(title=f"test_{i}") for i in range(5)]
    session.add_all(records)
    await session.commit()

    sorted_ids = sorted(r.id for r in records)
    min_id = sorted_ids[1]
    max_id = sorted_ids[3]

    pks = await repository.get_all_pks(min_id=min_id, max_id=max_id)
    assert len(pks) == 3
    assert all(min_id <= pk <= max_id for pk in pks)


async def test_get_partition_boundaries_empty(
    repository: SimpleSQLRepository,
) -> None:
    """Test get_partition_boundaries returns empty list when no records exist."""
    boundaries = await repository.get_partition_boundaries(partition_size=10)
    assert boundaries == []


async def test_get_partition_boundaries_single_partition(
    repository: SimpleSQLRepository, session: AsyncSession
) -> None:
    """Test get_partition_boundaries with fewer records than partition_size."""
    records = [SimpleSQLModel(title=f"test_{i}") for i in range(5)]
    session.add_all(records)
    await session.commit()

    boundaries = await repository.get_partition_boundaries(partition_size=10)
    assert len(boundaries) == 1
    min_id, max_id = boundaries[0]
    assert min_id == min(r.id for r in records)
    assert max_id == max(r.id for r in records)


async def test_get_partition_boundaries_multiple_partitions(
    repository: SimpleSQLRepository, session: AsyncSession
) -> None:
    """Test get_partition_boundaries creates correct number of partitions."""
    records = [SimpleSQLModel(title=f"test_{i}") for i in range(25)]
    session.add_all(records)
    await session.commit()

    boundaries = await repository.get_partition_boundaries(partition_size=10)
    assert len(boundaries) == 3

    all_ids = sorted(r.id for r in records)
    prior_max = None
    for min_id, max_id in boundaries:
        assert min_id <= max_id
        if prior_max:
            assert all_ids.index(min_id) == all_ids.index(prior_max) + 1
        assert min_id in all_ids
        assert max_id in all_ids
        prior_max = max_id

    assert boundaries[0][0] == all_ids[0]
    assert boundaries[-1][1] == all_ids[-1]


async def test_get_partition_boundaries_single_record(
    repository: SimpleSQLRepository, session: AsyncSession
) -> None:
    """Test get_partition_boundaries with a single record."""
    record = SimpleSQLModel(title="single")
    session.add(record)
    await session.commit()

    boundaries = await repository.get_partition_boundaries(partition_size=10)
    assert len(boundaries) == 1
    min_id, max_id = boundaries[0]
    assert min_id == record.id
    assert max_id == record.id


async def test_partition_and_retrieve_all_ids(
    repository: SimpleSQLRepository, session: AsyncSession
) -> None:
    """Test that partitioning and get_all_pks together retrieve all IDs exactly once."""
    # Create exactly 50 records for clean 5-partition split
    records = [SimpleSQLModel(title=f"test_{i}") for i in range(50)]
    session.add_all(records)
    await session.commit()

    all_record_ids = {r.id for r in records}

    # Partition into chunks of 10
    boundaries = await repository.get_partition_boundaries(partition_size=10)
    assert len(boundaries) == 5

    # Retrieve IDs from each partition and combine
    retrieved_ids: set = set()
    for min_id, max_id in boundaries:
        partition_ids = await repository.get_all_pks(min_id=min_id, max_id=max_id)
        # Verify no overlap with previously retrieved IDs
        assert retrieved_ids.isdisjoint(partition_ids), "Partitions should not overlap"
        retrieved_ids.update(partition_ids)

    # Verify we got all IDs exactly once
    assert retrieved_ids == all_record_ids
