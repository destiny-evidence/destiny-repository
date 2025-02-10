"""Utilities for managing databases for tests."""

import contextlib
import uuid
from collections.abc import AsyncIterator

import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy_utils.functions.orm import quote

from app.core.config import get_settings

settings = get_settings()


def admin_db_url() -> str:
    """Return a URL to the administrative databse."""
    base_url = get_settings().db_url
    db_name = base_url.path
    if db_name:
        return str(base_url).replace(db_name, "/postgres")
    return str(base_url) + "postgres"


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
    base_db_name = settings.db_url.path or ""
    tmp_db_url = str(settings.db_url).replace(base_db_name, "/" + tmp_db_name)
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
