"""Utilities for managing Elasticsearch indices for tests."""

from elasticsearch import AsyncElasticsearch

from app.system.routes import index_managers
from tests.persistence_models import SimpleDoc, simple_doc_index_manager

index_managers[SimpleDoc.Index.name] = simple_doc_index_manager


async def create_test_indices(client: AsyncElasticsearch):
    """Create all indices needed for tests."""
    for index_alias in index_managers:
        index_manager = index_managers[index_alias](client)
        await index_manager.initialize_index()


async def delete_test_indices(client: AsyncElasticsearch):
    """Delete all indices after tests."""
    for index_alias in index_managers:
        for index in await client.indices.get(index=f"{index_alias}*"):
            await client.indices.delete(index=index)


async def clean_test_indices(client: AsyncElasticsearch):
    """Delete all documents from all known indices after tests."""
    for index_alias in index_managers:
        index_manager = index_managers[index_alias](client)
        current_index_name = await index_manager.get_current_index_name()
        await client.indices.refresh(index=current_index_name)
        await index_manager.client.delete_by_query(
            index=current_index_name,
            body={"query": {"match_all": {}}},
            conflicts="proceed",
        )
        await client.indices.refresh(index=current_index_name)
