"""Utilities for managing databases for tests."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy_utils.functions.orm import quote

from app.core.config import get_settings
from app.persistence.sql.persistence import Base

settings = get_settings()


def admin_db_url() -> str:
    """Return a URL to the administrative database."""
    parsed_url = urlparse(get_settings().db_config.connection_string)
    query_params = parse_qs(parsed_url.query)

    # Replace the database name with 'postgres'
    new_path = "/postgres"
    new_url = parsed_url._replace(path=new_path)

    # Rebuild the URL with the original query parameters
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(new_url._replace(query=new_query))


def alembic_config_from_url(pg_url: str) -> AlembicConfig:
    """Provide python object, representing alembic.ini file."""
    base_path = settings.project_root
    config_path = str(base_path.joinpath("alembic.ini").absolute())
    config = AlembicConfig(
        file_=config_path,
    )
    # Replace path to alembic folder to absolute
    alembic_location = config.get_main_option("script_location") or "app/migrations"
    config.set_main_option(
        "script_location", str(base_path.joinpath(alembic_location).absolute())
    )
    config.set_main_option("sqlalchemy.url", pg_url)
    return config


@contextlib.asynccontextmanager
async def tmp_database(
    suffix: str = "", encoding: str = "utf8", template: str | None = None
) -> AsyncIterator[str]:
    """Context manager for creating new database and deleting it on exit."""
    tmp_db_name = f"{uuid.uuid4().hex}.tests_base.{suffix}"
    await create_database_async(tmp_db_name, encoding, template)
    parsed_url = urlparse(get_settings().db_config.connection_string)
    query_params = parse_qs(parsed_url.query)

    # Replace the database name with the temporary database name
    new_path = f"/{tmp_db_name}"
    new_url = parsed_url._replace(path=new_path)

    # Rebuild the URL with the original query parameters (except ssl which is
    # added back in)
    del query_params["ssl"]
    new_query = urlencode(query_params, doseq=True)
    tmp_db_url = urlunparse(new_url._replace(query=new_query))

    try:
        yield tmp_db_url
    finally:
        await drop_database_async(tmp_db_name)


# Next functions are copied from `sqlalchemy_utils` and slightly
# modified to support async. Maybe
async def create_database_async(
    db_name: str, encoding: str = "utf8", template: str | None = None
) -> None:
    """Create a temporary database to run our tests in."""
    engine = create_async_engine(admin_db_url(), isolation_level="AUTOCOMMIT")
    if not template:
        template = "template1"

    async with engine.begin() as conn:
        text = f"""CREATE DATABASE {quote(conn, db_name)}
        ENCODING {quote(conn, encoding)} TEMPLATE {quote(conn, template)}"""
        await conn.execute(
            sa.text(text),
        )

    await engine.dispose()


async def drop_database_async(db_name: str) -> None:
    """Drop the temporary database we ran our tests in."""
    engine = create_async_engine(admin_db_url(), isolation_level="AUTOCOMMIT")

    async with engine.begin() as conn:
        # Disconnect all users from the database we are dropping.
        text = f"""
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = '{db_name}'
        AND pid <> pg_backend_pid();
        """  # noqa: S608
        await conn.execute(sa.text(text))

        # Drop the database.
        text = f"DROP DATABASE {quote(conn,db_name)}"
        await conn.execute(sa.text(text))

    await engine.dispose()


async def clean_tables(conn: AsyncConnection) -> None:
    """Delete all data from all tables in the database."""
    # Clean tables. I tried
    # 1. Create new database using an empty `migrated_postgres_template` as template
    # (postgres could copy whole db structure)
    # 2. Do TRUNCATE after each test.
    # 3. Do DELETE after each test.
    # Doing DELETE FROM is the fastest
    # https://www.lob.com/blog/truncate-vs-delete-efficiently-clearing-data-from-a-postgres-table
    # BUT DELETE FROM query does not reset any AUTO_INCREMENT counters
    for table in reversed(Base.metadata.sorted_tables):
        # Check if table exists (handles test-only tables like simple_test_model)
        exists = await conn.run_sync(
            lambda sync_conn, table=table: sa.inspect(sync_conn).has_table(table.name)
        )
        if exists:
            await conn.execute(table.delete())
    await conn.commit()
