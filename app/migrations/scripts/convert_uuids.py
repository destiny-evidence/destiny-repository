"""
Part 2 of UUID4->UUID7 migration.

This script uses the `uuid_conversion` table created in part 1 to update all PKs and FKs
in the database from version 4 UUIDs to version 7 UUIDs.

!!! Important note - this is completely untested so far. Was put together speculatively
to explore feasibility. See also https://github.com/destiny-evidence/destiny-repository/issues/449.
"""

import asyncio

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger, logger_configurer
from app.core.telemetry.otel import configure_otel
from app.migrations.scripts.uuid_conversion_table import (
    CONVERSION_TABLE_NAME,
    get_all_tables,
)
from app.persistence.sql.session import db_manager

settings = get_settings()
logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

logger_configurer.configure_console_logger(
    log_level=settings.log_level, rich_rendering=settings.running_locally
)

if settings.otel_config and settings.otel_enabled:
    # Always instrument SQL for migrations when OTEL is enabled
    settings.otel_config.instrument_sql = True

    configure_otel(
        settings.otel_config,
        "db-migrator",
        settings.app_version,
        settings.env,
        settings.trace_repr,
    )


async def get_fk_references(
    connection: AsyncConnection, table: str
) -> list[tuple[str, str]]:
    """Get all foreign key references to a given table's PK."""
    result = await connection.execute(
        """
        SELECT
            tc.table_name AS fk_table,
            kcu.column_name AS fk_column
        FROM
            information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE
            tc.constraint_type = 'FOREIGN KEY'
            AND ccu.table_name = :table
            AND ccu.column_name = 'id';
        """,
        {"table": table},
    )
    return [(row.fk_table, row.fk_column) for row in result.fetchall()]


async def perform_uuid_migration(
    connection: AsyncConnection, table: str, fks: list[tuple[str, str]]
) -> None:
    """
    Perform UUID migration for a given table and its foreign keys.

    This is idempotent - once run successfully once, the join will find no rows to
    update.
    """
    await connection.execute(
        f"""
        UPDATE {table} AS t
        SET id = c.new_id
        FROM {CONVERSION_TABLE_NAME} AS c
        WHERE t.id = c.old_id;
        """  # noqa: S608
    )
    for fk_table, fk_column in fks:
        await connection.execute(
            f"""
            UPDATE {fk_table} AS ft
            SET {fk_column} = c.new_id
            FROM {CONVERSION_TABLE_NAME} AS c
            WHERE ft.{fk_column} = c.old_id;
            """  # noqa: S608
        )
    await connection.commit()


async def perform_non_fk_table_updates(
    connection: AsyncConnection,
) -> None:
    """Update any hanging IDs that are not FKs."""
    await connection.execute(
        f"""
        UPDATE enhancement e
        SET derived_from = array_agg(c.new_id)
        FROM {CONVERSION_TABLE_NAME} AS c
        WHERE c.old_id = ANY(e.derived_from)
        GROUP BY e.id;
        """  # noqa: S608
    )
    await connection.commit()


async def main() -> None:
    """Perform the UUID migration."""
    async with db_manager.connect() as connection:
        tables = await get_all_tables(connection)
        for table in tables:
            logger.info("Processing PKs for UUID migration.", table=table)
            fks = await get_fk_references(connection, table)
            logger.info("Found FK references.", table=table, fk_count=len(fks))
            await perform_uuid_migration(connection, table, fks)
        await perform_non_fk_table_updates(connection)


if __name__ == "__main__":
    asyncio.run(main())
