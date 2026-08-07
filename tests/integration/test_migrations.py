"""Test Alembic migration from 1d8078bc0a95 to 41a6980bb04e."""

import datetime
from uuid import uuid7

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
                "id": (ref_id := str(uuid7())),
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
                "id": (rob_id := str(uuid7())),
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
                "id": (pe_id := uuid7()),
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
                "id": (ref_id := str(uuid7())),
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
                "id": (id_id := str(uuid7())),
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
                "id": (enh_id := str(uuid7())),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("migration_id", ["73a049948581"])
async def test_pending_enhancement_unique_index_fails_fast_on_duplicates(
    db_at_migration: str,
) -> None:
    """The (request, reference) unique-index migration refuses pre-existing dupes."""
    db_url = db_at_migration
    engine = create_async_engine(db_url, future=True)
    now = datetime.datetime.now(datetime.UTC)
    ref_id, rob_id, req_id = str(uuid7()), str(uuid7()), str(uuid7())

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO reference (id, visibility, created_at, updated_at) "
                "VALUES (:id, 'public', :now, :now)"
            ),
            {"id": ref_id, "now": now},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO robot (id, name, description, owner, client_secret, "
                "created_at, updated_at) "
                "VALUES (:id, 'R', 'd', 'o@e.com', 's', :now, :now)"
            ),
            {"id": rob_id, "now": now},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO enhancement_request (id, reference_ids, robot_id, "
                "request_status, created_at, updated_at) "
                "VALUES (:id, '{}'::uuid[], :robot_id, 'received', :now, :now)"
            ),
            {"id": req_id, "robot_id": rob_id, "now": now},
        )
        # Two original (retry_of NULL) pending enhancements for the same
        # (request, reference): exactly what the new index forbids.
        for _ in range(2):
            await conn.execute(
                sa.text(
                    "INSERT INTO pending_enhancement (id, reference_id, robot_id, "
                    "enhancement_request_id, status, expires_at, created_at, "
                    "updated_at) "
                    "VALUES (:id, :ref, :rob, :req, 'pending', :now, :now, :now)"
                ),
                {
                    "id": str(uuid7()),
                    "ref": ref_id,
                    "rob": rob_id,
                    "req": req_id,
                    "now": now,
                },
            )

    with pytest.raises(RuntimeError, match="multiple original pending enhancements"):
        await run_migration(db_url, "9b2f1c4d7e83")

    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("migration_id", ["9b2f1c4d7e83"])
async def test_duplicate_decision_provenance_migration_classifies_known_manual_eef(
    db_at_migration: str,
) -> None:
    """Classify verified EEF manual decisions without guessing other history."""
    engine = create_async_engine(db_at_migration, future=True)
    now = datetime.datetime.now(datetime.UTC)
    eef_record_id, other_record_id = str(uuid7()), str(uuid7())
    eef_batch_id, other_batch_id = str(uuid7()), str(uuid7())
    canonical_target_id = str(uuid7())
    (
        manual_eef_canonical_id,
        manual_eef_duplicate_id,
        manual_eef_inactive_id,
        automatic_eef_id,
        unsearchable_eef_id,
        other_id,
    ) = (str(uuid7()) for _ in range(6))

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO reference (id, visibility, created_at, updated_at) "
                "VALUES (:id, 'public', :now, :now)"
            ),
            {"id": canonical_target_id, "now": now},
        )
        for record_id, source_name in (
            (eef_record_id, "eef-eppi-review-export-2026"),
            (other_record_id, "openalex"),
        ):
            await conn.execute(
                sa.text(
                    "INSERT INTO import_record "
                    "(id, searched_at, processor_name, processor_version, "
                    "expected_reference_count, source_name, status, created_at, "
                    "updated_at) VALUES "
                    "(:id, :now, 'test', '1', 1, :source, 'completed', :now, :now)"
                ),
                {"id": record_id, "source": source_name, "now": now},
            )
        for batch_id, record_id in (
            (eef_batch_id, eef_record_id),
            (other_batch_id, other_record_id),
        ):
            await conn.execute(
                sa.text(
                    "INSERT INTO import_batch "
                    "(id, import_record_id, storage_url, created_at, updated_at) "
                    "VALUES (:id, :record_id, :url, :now, :now)"
                ),
                {
                    "id": batch_id,
                    "record_id": record_id,
                    "url": f"https://example.com/{batch_id}",
                    "now": now,
                },
            )

        # (decision id, batch, detail, determination, canonical, active)
        decisions = (
            (manual_eef_canonical_id, eef_batch_id, None, "canonical", None, True),
            (
                manual_eef_duplicate_id,
                eef_batch_id,
                None,
                "duplicate",
                canonical_target_id,
                True,
            ),
            (manual_eef_inactive_id, eef_batch_id, None, "canonical", None, False),
            (
                automatic_eef_id,
                eef_batch_id,
                "Automatic decision",
                "canonical",
                None,
                True,
            ),
            (unsearchable_eef_id, eef_batch_id, None, "unsearchable", None, True),
            (other_id, other_batch_id, None, "canonical", None, True),
        )
        for (
            decision_id,
            batch_id,
            detail,
            determination,
            canonical_id,
            active,
        ) in decisions:
            reference_id = str(uuid7())
            await conn.execute(
                sa.text(
                    "INSERT INTO import_result "
                    "(id, import_batch_id, status, reference_id, created_at, "
                    "updated_at) "
                    "VALUES (:id, :batch_id, 'imported', :reference_id, :now, :now)"
                ),
                {
                    "id": str(uuid7()),
                    "batch_id": batch_id,
                    "reference_id": reference_id,
                    "now": now,
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO reference_duplicate_decision "
                    "(id, reference_id, active_decision, candidate_canonical_ids, "
                    "duplicate_determination, canonical_reference_id, detail, "
                    "created_at, updated_at) "
                    "VALUES (:id, :reference_id, :active, '{}', :determination, "
                    ":canonical_id, :detail, :now, :now)"
                ),
                {
                    "id": decision_id,
                    "reference_id": reference_id,
                    "active": active,
                    "determination": determination,
                    "canonical_id": canonical_id,
                    "detail": detail,
                    "now": now,
                },
            )

    await run_migration(db_at_migration, "6df1b2b092ed")

    async with engine.begin() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT id, decision_authority, decision_trigger "
                "FROM reference_duplicate_decision"
            )
        )
        provenance = {
            str(row.id): (row.decision_authority, row.decision_trigger)
            for row in result
        }

    classified = ("person", "manual_api")
    untouched = ("unclassified", "unclassified")
    # Both determinations in the predicate, and activeness is deliberately ignored.
    assert provenance[manual_eef_canonical_id] == classified
    assert provenance[manual_eef_duplicate_id] == classified
    assert provenance[manual_eef_inactive_id] == classified
    # Each excluded for a different clause: detail, determination, source.
    assert provenance[automatic_eef_id] == untouched
    assert provenance[unsearchable_eef_id] == untouched
    assert provenance[other_id] == untouched
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("migration_id", ["9b2f1c4d7e83"])
async def test_duplicate_decision_provenance_accepts_pre_migration_inserts(
    db_at_migration: str,
) -> None:
    """A rolling deploy keeps the old revision inserting without the new columns."""
    engine = create_async_engine(db_at_migration, future=True)
    await run_migration(db_at_migration, "6df1b2b092ed")

    now = datetime.datetime.now(datetime.UTC)
    decision_id = str(uuid7())
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO reference_duplicate_decision "
                "(id, reference_id, active_decision, candidate_canonical_ids, "
                "duplicate_determination, created_at, updated_at) "
                "VALUES (:id, :reference_id, true, '{}', 'canonical', :now, :now)"
            ),
            {"id": decision_id, "reference_id": str(uuid7()), "now": now},
        )
        provenance = (
            await conn.execute(
                sa.text(
                    "SELECT decision_authority, decision_trigger "
                    "FROM reference_duplicate_decision WHERE id = :id"
                ),
                {"id": decision_id},
            )
        ).one()

    assert provenance == ("unclassified", "unclassified")
    await engine.dispose()
