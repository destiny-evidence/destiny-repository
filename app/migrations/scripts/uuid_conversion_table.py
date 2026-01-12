"""
Part 1 of UUID4->UUID7 migration.

This script:
- Creates a new table `uuid_conversion` with columns `old_id` and `new_id`.
- Finds all existing PK IDs in all tables that are version 4 UUIDs.
- Uses `created_at` on each record to generate a version 7 UUID.
- Saves the mapping from old to new UUIDs in the `uuid_conversion` table.

!!! Important note - this is completely untested so far. Was put together speculatively
to explore feasibility. See also https://github.com/destiny-evidence/destiny-repository/issues/449.
"""

import asyncio

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger, logger_configurer
from app.core.telemetry.otel import configure_otel
from app.migrations.scripts.custom_uuid7 import uuid7
from app.persistence.sql.session import db_manager

CONVERSION_TABLE_NAME = "uuid_conversion"
BUFFER_SIZE = 100_000

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


@tracer.start_as_current_span("Create Conversion Table")
async def create_uuid_conversion_table(connection: AsyncConnection) -> None:
    """Create the uuid conversion table."""
    await connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CONVERSION_TABLE_NAME} (
            old_id UUID PRIMARY KEY UNIQUE NOT NULL,
            new_id UUID UNIQUE NOT NULL
        );
        """
    )
    await connection.commit()
    logger.info("Created table.", table=CONVERSION_TABLE_NAME)


@tracer.start_as_current_span("Get All Tables")
async def get_all_tables(connection: AsyncConnection) -> set[str]:
    """Get all user-defined tables in the public schema."""
    result = await connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        AND table_name != :conversion_table_name;
        """,
        {"conversion_table_name": CONVERSION_TABLE_NAME},
    )
    return {row[0] for row in result.fetchall()}


@tracer.start_as_current_span("Populate Conversion Table")
async def populate_uuid_conversion_table(
    connection: AsyncConnection,
    tables: set[str],
) -> None:
    """Populate the uuid conversion table."""
    selects = [
        f"""
        SELECT id, EXTRACT(EPOCH FROM created_at) * 1000 AS created_at_ms
        FROM {table_name}
        WHERE uuid_extract_version(id) = 4
        """  # noqa: S608
        for table_name in tables
    ]
    processed = 0
    async with await connection.execution_options(yield_per=BUFFER_SIZE).execute(
        " UNION ALL ".join(selects) + " ORDER BY created_at_ms;"
    ) as response:
        for partition in response.partitions():
            id_map = [
                {"old_id": row["id"], "new_id": uuid7(int(row["created_at_ms"]))}
                for row in partition
            ]
            await connection.execute(
                f"""
                INSERT INTO {CONVERSION_TABLE_NAME} (old_id, new_id)
                VALUES (:old_id, :new_id);
                """,  # noqa: S608
                id_map,
            )
            processed += len(id_map)
            logger.info(
                "Processed UUID conversion batch.",
                batch_size=len(id_map),
                total_processed=processed,
            )


@tracer.start_as_current_span("UUID Conversion Table Generation")
async def main() -> None:
    """Perform the script."""
    async with db_manager.connect() as connection:
        logger.info("Starting UUID conversion table generation.")
        await create_uuid_conversion_table(connection)
        logger.info("Created conversion table.", table=CONVERSION_TABLE_NAME)
        tables = await get_all_tables(connection)
        logger.info("Found existing tables.", table_count=len(tables))
        await populate_uuid_conversion_table(connection, tables)
        await connection.commit()
        logger.info("Completed UUID conversion table generation.")


if __name__ == "__main__":
    asyncio.run(main())
