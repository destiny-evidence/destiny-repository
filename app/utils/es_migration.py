"""Elasticsearch migration."""

import asyncio

from app.core.config import get_settings
from app.persistence.es.client import es_manager, indices
from app.persistence.es.index_manager import IndexManager


async def run_migration() -> None:
    """Run any migrations for the elasticsearch setup."""
    es_config = get_settings().es_config

    await es_manager.init(es_config)

    async with es_manager.client() as client:
        for index in indices:
            manager = IndexManager(index, index.Index.name, client)
            # If the index does not exist, migrating will create it.
            await manager.migrate()

    await es_manager.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
