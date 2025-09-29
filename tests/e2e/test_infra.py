"""Diagnostic test to ensure the test infra is working."""

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_infra(destiny_client_v1: httpx.AsyncClient, pg_session: AsyncSession):
    """Diagnostic test to ensure the test infra is working."""
    (
        await destiny_client_v1.get(
            "system/healthcheck/", params={"azure_blob_storage": False}
        )
    ).raise_for_status()

    # Check alembic migrations have been applied
    version = await pg_session.execute(text("SELECT version_num FROM alembic_version"))
    version_value = version.scalar()
    assert version_value
    await pg_session.execute(text("SELECT * FROM reference"))
