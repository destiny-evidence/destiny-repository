"""Managment of the database session."""

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.exceptions import UOWError


class AsyncDatabaseSessionManager:
    """Manages database sessions."""

    def __init__(self) -> None:
        """Init AsyncDatabaseSessionManager."""
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def init(self, db_url: str) -> None:
        """Initialize the database manager."""
        connect_args: dict[str, Any] = {}
        self._engine = create_async_engine(
            url=db_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._sessionmaker = async_sessionmaker(
            bind=self._engine,
            # https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#asyncio-orm-avoid-lazyloads
            # This is safe to use because the object is transient through the
            # persistence layer
            expire_on_commit=False,
        )

    async def close(self) -> None:
        """Close all database connections and dispose of references."""
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a database session."""
        if self._sessionmaker is None:
            msg = "AsyncDatabaseSessionManager is not initialized"
            raise UOWError(msg)
        async with self._sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        """Yield a database connection."""
        if self._engine is None:
            msg = "AsyncDatabaseSessionManager is not initialized"
            raise UOWError(msg)
        async with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise


db_manager = AsyncDatabaseSessionManager()


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Yield a session for use in the app.

    This is designed to be used as FastAPI dependency:

    ```
    Depends(get_session)
    ```
    """
    async with db_manager.session() as session:
        yield session
