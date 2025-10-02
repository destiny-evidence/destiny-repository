"""Elasticsearch migration."""

import asyncio

from app.core.config import get_settings
from app.persistence.es.client import es_manager, indices
from app.persistence.es.migration import IndexManager


async def run_initialization() -> None:
    """Run any initialization tasks, such as setting up indices."""
    es_config = get_settings().es_config

    await es_manager.init(es_config)

    async with es_manager.client() as client:
        for index in indices:
            manager = IndexManager(index, index.Index.name, client)
            await manager.initialize_index()

    await es_manager.close()


if __name__ == "__main__":
    asyncio.run(run_initialization())
