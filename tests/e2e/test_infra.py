"""Diagnostic test to ensure the test infra is working."""

import asyncpg
import httpx


async def test_infra(
    destiny_client_v1: httpx.AsyncClient, pg_session: asyncpg.Connection
):
    """Diagnostic test to ensure the test infra is working."""
    (
        await destiny_client_v1.get(
            "system/healthcheck/", params={"azure_blob_storage": False}
        )
    ).raise_for_status()

    # Check alembic migrations have been applied
    version = await pg_session.fetchrow("SELECT version_num FROM alembic_version;")
    assert version
    await pg_session.execute("SELECT * FROM reference;")
