"""Confirm the evaluation driver's read-only guard reaches the real transaction."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.persistence_models import SimpleSQLModel


async def test_read_only_transaction_refuses_a_write(session: AsyncSession) -> None:
    """
    A write fails once the transaction is read-only.

    SQLAlchemy opens the transaction on this first statement, so the guard has to
    land inside the transaction the ORM then reuses, not a discarded one.
    """
    await session.execute(text("SET TRANSACTION READ ONLY"))

    session.add(SimpleSQLModel(title="written"))
    with pytest.raises((DBAPIError, InternalError), match="read-only transaction"):
        await session.flush()


async def test_reads_still_work_in_a_read_only_transaction(
    session: AsyncSession,
) -> None:
    """The guard must not cost the driver the queries it exists to run."""
    await session.execute(text("SET TRANSACTION READ ONLY"))

    result = await session.execute(text("SELECT count(*) FROM reference"))

    assert result.scalar() == 0
