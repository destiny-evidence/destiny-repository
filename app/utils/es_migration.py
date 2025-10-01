import asyncio

from app.domain.references.models.es import ReferenceDocument
from app.persistence.es.client import es_manager
from app.persistence.es.migration import IndexMigrationManager
from app.core.config import get_settings


async def run_initialization() -> None:
    """Run any initialization tasks, such as setting up indices."""
    es_config = get_settings().es_config

    await es_manager.init(es_config)

    async with es_manager.client() as client:
        manager = IndexMigrationManager(ReferenceDocument, "reference", client)
        await manager.initialize_index()


if __name__ == "__main__":
    asyncio.run(run_initialization())
