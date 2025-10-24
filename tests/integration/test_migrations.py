"""Test Alembic migration from 1d8078bc0a95 to 41a6980bb04e."""

import datetime
import uuid

import pytest
import sqlalchemy as sa
from alembic.command import upgrade
from sqlalchemy.ext.asyncio import create_async_engine

from tests import conftest
from tests.db_utils import alembic_config_from_url, tmp_database


async def run_migration(db_url: str, target_revision: str) -> None:
    """Run Alembic migration to the specified target revision."""
    alembic_config = alembic_config_from_url(db_url)
    conftest.MIGRATION_TASK = None
    upgrade(alembic_config, target_revision)
    if conftest.MIGRATION_TASK:
        await conftest.MIGRATION_TASK


@pytest.fixture
async def db_1d80():
    """Create temporary database and applies migrations up to 1d8078bc0a95."""
    async with tmp_database("pytest_migration") as tmp_url:
        await run_migration(tmp_url, "1d8078bc0a95")
        yield tmp_url


@pytest.mark.asyncio
async def test_migrate_1d80_to_41a69(db_1d80: str) -> None:
    """Test migrating from 1d8078bc0a95 to 41a6980bb04e, including data migration."""
    db_url = db_1d80
    engine = create_async_engine(db_url, future=True)

    # Insert a pending_enhancement row with status 'ACCEPTED'
    async with engine.begin() as conn:
        # Insert minimal required reference and robot for FKs
        now = datetime.datetime.now(datetime.UTC)
        await conn.execute(
            sa.text(
                "INSERT INTO reference (id, visibility, created_at, updated_at) VALUES "
                "(:id, :visibility, :created_at, :updated_at)"
            ),
            {
                "id": (ref_id := str(uuid.uuid4())),
                "visibility": "public",
                "created_at": now,
                "updated_at": now,
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO robot "
                "(id, name, description, owner, client_secret, created_at, updated_at) "
                "VALUES (:id, :name, :desc, :owner, :secret, :created_at, :updated_at)"
            ),
            {
                "id": (rob_id := str(uuid.uuid4())),
                "name": "Test Robot",
                "desc": "desc",
                "owner": "owner@example.com",
                "secret": "secret",
                "created_at": now,
                "updated_at": now,
            },
        )

        # Insert pending_enhancement with status 'ACCEPTED'
        await conn.execute(
            sa.text(
                "INSERT INTO pending_enhancement "
                "(id, reference_id, robot_id, status, enhancement_request_id, source, "
                "created_at, updated_at) "
                "VALUES "
                "(:id, :reference_id, :robot_id, :status, NULL, 'test_source', "
                ":created_at, :updated_at)"
            ),
            {
                "id": (pe_id := uuid.uuid4()),
                "reference_id": ref_id,
                "robot_id": rob_id,
                "status": "ACCEPTED",
                "created_at": now,
                "updated_at": now,
            },
        )

    # Apply migrations up to 41a6980bb04e
    await run_migration(db_url, "7afd162b774a")
    await run_migration(db_url, "41a6980bb04e")

    # Verify migration results
    async with engine.begin() as conn:
        # Check status changed to PROCESSING
        result = await conn.execute(
            sa.text(
                "SELECT status, expires_at, retry_of "
                "FROM pending_enhancement WHERE id = :id"
            ),
            {"id": pe_id},
        )
        row = result.first()
        assert row is not None
        assert row.status == "PROCESSING"
        assert row.expires_at == datetime.datetime(
            1970, 1, 1, 0, 0, tzinfo=datetime.UTC
        )
        assert row.retry_of is None

    await engine.dispose()
