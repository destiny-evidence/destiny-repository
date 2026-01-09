"""Test Alembic migration from 1d8078bc0a95 to 41a6980bb04e."""

import datetime
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.command import upgrade
from destiny_sdk.enhancements import EnhancementType
from destiny_sdk.identifiers import ExternalIdentifierType
from sqlalchemy.ext.asyncio import create_async_engine

from tests import conftest
from tests.db_utils import alembic_config_from_url, tmp_database
from tests.factories import AbstractContentEnhancementFactory


async def run_migration(db_url: str, target_revision: str) -> None:
    """Run Alembic migration to the specified target revision."""
    alembic_config = alembic_config_from_url(db_url)
    conftest.MIGRATION_TASK = None
    upgrade(alembic_config, target_revision)
    if conftest.MIGRATION_TASK:
        await conftest.MIGRATION_TASK


@pytest_asyncio.fixture
async def db_at_migration(migration_id: str):
    """Create temporary database and applies migrations up to the migration id."""
    async with tmp_database("pytest_migration") as tmp_url:
        await run_migration(tmp_url, migration_id)
        yield tmp_url


@pytest.mark.asyncio
@pytest.mark.parametrize("migration_id", ["1d8078bc0a95"])
async def test_migrate_1d80_to_41a69(db_at_migration: str) -> None:
    """Test migrating from 1d8078bc0a95 to 41a6980bb04e, including data migration."""
    db_url = db_at_migration
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
                "id": (ref_id := str(uuid.uuid7())),
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
                "id": (rob_id := str(uuid.uuid7())),
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
                "id": (pe_id := uuid.uuid7()),
                "reference_id": ref_id,
                "robot_id": rob_id,
                "status": "ACCEPTED",
                "created_at": now,
                "updated_at": now,
            },
        )

    # Apply migrations up to 41a6980bb04e
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


@pytest.mark.asyncio
@pytest.mark.parametrize("migration_id", ["41a6980bb04e"])
async def test_migrate_41a69_to_1a717(db_at_migration: str) -> None:
    """
    Test migrating from 41a6980bb04e to 1a717e152dff.

    Removing enhancement_type enum.
    Removing external_identifier_type enum.
    """
    db_url = db_at_migration
    engine = create_async_engine(db_url, future=True)

    async with engine.begin() as conn:
        now = datetime.datetime.now(datetime.UTC)

        # Insert a reference
        await conn.execute(
            sa.text(
                "INSERT INTO reference (id, visibility, created_at, updated_at) "
                "VALUES (:id, :visibility, :created_at, :updated_at)"
            ),
            {
                "id": (ref_id := str(uuid.uuid7())),
                "visibility": "public",
                "created_at": now,
                "updated_at": now,
            },
        )

        # Insert an external identifier
        await conn.execute(
            sa.text(
                "INSERT INTO external_identifier (id, reference_id, identifier_type, "
                "identifier , created_at, updated_at) "
                "VALUES (:id, :reference_id, :identifier_type, "
                ":identifier, :created_at, :updated_at)"
            ),
            {
                "id": (id_id := str(uuid.uuid7())),
                "reference_id": ref_id,
                "identifier": "10.1234/sampledoi",
                "identifier_type": ExternalIdentifierType.DOI,
                "created_at": now,
                "updated_at": now,
            },
        )

        # Insert an enhancement
        await conn.execute(
            sa.text(
                "INSERT INTO enhancement"
                "(id, visibility, source, reference_id, enhancement_type, "
                "content, created_at, updated_at)"
                "VALUES (:id, :visibility, :source, :reference_id, :enhancement_type, "
                ":content, :created_at, :updated_at)"
            ),
            {
                "id": (enh_id := str(uuid.uuid7())),
                "visibility": "public",
                "source": "test_source",
                "reference_id": ref_id,
                "enhancement_type": EnhancementType.ABSTRACT,
                "content": AbstractContentEnhancementFactory.build().model_dump_json(),
                "created_at": now,
                "updated_at": now,
            },
        )

    # Apply migrations up to 1a717e152dff
    # Applies removal of both enum types
    await run_migration(db_url, "1a717e152dff")

    # Verify enhancement_type enum has been removed
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT typname FROM pg_type "
                "WHERE pg_type.typcategory='E' "
                "AND (typname='enhancement_type' OR typname='external_identifier_type')"
            ),
        )

        assert result.rowcount == 0

    # Verify that the external identifier still has an identifier type of doi
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.text("SELECT identifier_type FROM external_identifier WHERE id = :id"),
            {"id": id_id},
        )
        row = result.first()
        assert row is not None
        assert row.identifier_type == ExternalIdentifierType.DOI

    # Verify that the enhancement still has an enhancement type of abstract
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.text("SELECT enhancement_type " "FROM enhancement WHERE id = :id"),
            {"id": enh_id},
        )
        row = result.first()
        assert row is not None
        assert row.enhancement_type == EnhancementType.ABSTRACT

    await engine.dispose()
