"""Supporting code for migrations."""

import asyncio
import os
from contextvars import ContextVar
from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.runtime.environment import EnvironmentContext
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.domain.imports.models.sql import *  # noqa: F403
from app.persistence.sql.declarative_base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
settings = get_settings()


if "PYTEST_CURRENT_TEST" not in os.environ:
    config.set_main_option("sqlalchemy.url", str(settings.db_url))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

ctx_var: ContextVar[dict[str, Any]] = ContextVar("ctx_var")


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:  # noqa: D103
    try:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()
    except AttributeError:
        # When we're running migrations inside tests, the context won't have
        # been set up.  So we catch the AttributeError and set up our own
        # context (from the data we've) stashed outside our async context. It's
        # a bit of a hack but it seems to work.
        context_data = ctx_var.get()
        with EnvironmentContext(
            config=context_data["config"],
            script=context_data["script"],
            **context_data["opts"],
        ):
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations with an Engine and associate a connection with the context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    try:
        _current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop, let's do it ourselves!
        asyncio.run(run_async_migrations())
        return

    from tests import conftest

    ctx_var.set(
        {
            "config": context.config,
            "script": context.script,
            "opts": context._proxy.context_opts,  # noqa: SLF001 # type: ignore[attr-defined]
        }
    )
    conftest.MIGRATION_TASK = asyncio.create_task(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
