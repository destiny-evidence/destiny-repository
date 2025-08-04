"""Management of the Elasticsearch client."""

import contextlib
from collections.abc import AsyncIterator

from elasticsearch import AsyncElasticsearch
from elasticsearch.exceptions import BadRequestError
from structlog import get_logger

from app.core.config import ESConfig
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)

logger = get_logger(__name__)
indices = (ReferenceDocument, RobotAutomationPercolationDocument)


class AsyncESClientManager:
    """Manages AsyncElasticsearch client lifecycle."""

    def __init__(self) -> None:
        """Initialize the AsyncESClientManager."""
        self._client: AsyncElasticsearch | None = None

    async def init(self, es_config: ESConfig) -> None:
        """Initialize the Elasticsearch client manager."""
        if self._client is None:
            if es_config.es_insecure_url:
                self._client = AsyncElasticsearch(
                    str(es_config.es_insecure_url),
                    retry_on_timeout=es_config.retry_on_timeout,
                    max_retries=es_config.max_retries,
                )
            elif es_config.uses_api_key:
                self._client = AsyncElasticsearch(
                    cloud_id=es_config.cloud_id,
                    api_key=es_config.api_key,
                    retry_on_timeout=es_config.retry_on_timeout,
                    max_retries=es_config.max_retries,
                )
            elif es_config.es_user and es_config.es_pass and es_config.es_ca_path:
                self._client = AsyncElasticsearch(
                    hosts=es_config.es_hosts,
                    ca_certs=str(es_config.es_ca_path),
                    basic_auth=(es_config.es_user, es_config.es_pass),
                    retry_on_timeout=es_config.retry_on_timeout,
                    max_retries=es_config.max_retries,
                )
            else:
                msg = "No valid Elasticsearch configuration provided."
                raise ValueError(msg)

        for index in indices:
            exists = await self._client.indices.exists(index=index.Index.name)
            if not exists:
                msg = f"Creating index {index.Index.name}"
                logger.info(msg)
                try:
                    await index.init(using=self._client)
                except BadRequestError as e:
                    # Handle race condition where index was created between check/init
                    if "resource_already_exists_exception" in str(e):
                        msg = f"Index {index.Index.name} already exists, skipping"
                        logger.info(msg)
                    else:
                        raise

    async def close(self) -> None:
        """Close the Elasticsearch client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    @contextlib.asynccontextmanager
    async def client(self) -> AsyncIterator[AsyncElasticsearch]:
        """Yield the AsyncElasticsearch client as an async context manager."""
        if self._client is None:
            msg = "AsyncESClientManager is not initialized"
            raise RuntimeError(msg)
        try:
            yield self._client
        finally:
            pass  # Optionally handle per-request cleanup


es_manager = AsyncESClientManager()


async def get_client() -> AsyncIterator[AsyncElasticsearch]:
    """
    Yield an AsyncElasticsearch client for FastAPI dependency injection.

    Usage: Depends(get_client)
    """
    async with es_manager.client() as client:
        yield client
