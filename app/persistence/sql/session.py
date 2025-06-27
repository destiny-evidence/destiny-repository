"""Managment of the database session."""

import contextlib
import datetime
from collections.abc import AsyncIterator
from typing import Any

from azure.identity import DefaultAzureCredential
from sqlalchemy import event
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from app.core.config import DatabaseConfig
from app.core.exceptions import UOWError
from app.core.logger import get_logger

logger = get_logger()


class AsyncDatabaseSessionManager:
    """Manages database sessions."""

    def __init__(self) -> None:
        """Init AsyncDatabaseSessionManager."""
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._azure_credentials = DefaultAzureCredential()

    def init(self, db_config: DatabaseConfig, app_name: str) -> None:
        """Initialize the database manager."""
        connect_args: dict[str, Any] = {
            "server_settings": {
                "application_name": app_name,
            },
        }
        self._engine = create_async_engine(
            url=db_config.connection_string,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

        if db_config.passwordless:
            # This is (more or less) as recommended in SQLAlchemy docs
            # https://docs.sqlalchemy.org/en/20/core/engines.html#generating-dynamic-authentication-tokens
            # https://docs.sqlalchemy.org/en/20/dialects/mssql.html#mssql-pyodbc-access-tokens

            # Cold boot appears to be slow - here we kick off the first token retrieval
            # so that the first request is not delayed by it.
            self._azure_credentials.get_token(str(db_config.azure_db_resource_url))

            @event.listens_for(self._engine.sync_engine, "do_connect")
            def provide_token(
                _dialect: Dialect,
                _conn_rec: ConnectionPoolEntry,
                _cargs: list[Any],
                cparams: dict[str, Any],
            ) -> None:
                # We can consider a TTL cache here but from experimentation it seems
                # Azure does some caching of its own
                def get_token() -> str:
                    logger.info("Retrieving DB access token from Azure")
                    token = self._azure_credentials.get_token(
                        str(db_config.azure_db_resource_url)
                    )
                    logger.info(
                        "DB access token retrieved from Azure",
                        extra={
                            "expires_at": datetime.datetime.fromtimestamp(
                                token.expires_on, tz=datetime.UTC
                            ).isoformat(),
                        },
                    )
                    return token.token

                # Apply it to keyword arguments
                cparams["password"] = get_token()

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
