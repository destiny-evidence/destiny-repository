"""Setup fixtures for all tests."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from alembic.command import upgrade
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.core.config import get_settings
from app.core.db import DatabaseSessionManager, db_manager
from tests.db_utils import alembic_config_from_url, tmp_database

settings = get_settings()
MIGRATION_TASK: asyncio.Task | None = None

logging.getLogger("asyncio").setLevel("DEBUG")


@pytest.fixture(scope="session", autouse=True)
def anyio_backend() -> tuple[str, dict[str, Any]]:
    """Specify the anyio backend for async tests."""
    return "asyncio", {"use_uvloop": True}


@pytest.fixture(scope="session")
async def migrated_postgres_template() -> AsyncGenerator[str]:
    """
    Create temporary database and applies migrations.

    Has "session" scope, so is called only once per tests run.
    """
    async with tmp_database("pytest") as tmp_url:
        alembic_config = alembic_config_from_url(tmp_url)

        # It is important to always close the connections at the end of such migrations,
        # or we will get errors like `source database is being accessed by other users`

        upgrade(alembic_config, "head")
        if MIGRATION_TASK:
            await MIGRATION_TASK

        yield tmp_url


@pytest.fixture(scope="session")
async def sessionmanager_for_tests(
    migrated_postgres_template: str,
) -> AsyncGenerator[DatabaseSessionManager]:
    """Build shared session manager for tests."""
    db_manager.init(db_url=migrated_postgres_template)
    # can add another init (redis, etc...)
    yield db_manager
    await db_manager.close()


@pytest.fixture
async def session(
    sessionmanager_for_tests: DatabaseSessionManager,
) -> AsyncGenerator[AsyncSession]:
    """Yield the session for the test and cleanup tables."""
    async with sessionmanager_for_tests.session() as session:
        yield session
    # Clean tables. I tried
    # 1. Create new database using an empty `migrated_postgres_template` as template
    # (postgres could copy whole db structure)
    # 2. Do TRUNCATE after each test.
    # 3. Do DELETE after each test.
    # Doing DELETE FROM is the fastest
    # https://www.lob.com/blog/truncate-vs-delete-efficiently-clearing-data-from-a-postgres-table
    # BUT DELETE FROM query does not reset any AUTO_INCREMENT counters
    async with sessionmanager_for_tests.connect() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            # Clean tables in such order that tables which depend on another go first
            await conn.execute(table.delete())
        await conn.commit()
