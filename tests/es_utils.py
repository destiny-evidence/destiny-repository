"""Utilities for managing Elasticsearch indices for tests."""

from elasticsearch import AsyncElasticsearch

from app.persistence.es.client import indices
from app.persistence.es.index_manager import IndexManager


async def create_test_indices(client: AsyncElasticsearch):
    """Create all indices needed for tests."""
    for index in indices:
        index_manager = IndexManager(index, client)
        await index_manager.initialize_index()


async def delete_test_indices(client: AsyncElasticsearch):
    """Delete all indices after tests."""
    for index in indices:
        index_manager = IndexManager(index, client)
        current_index_name = await index_manager.get_current_index_name()
        if current_index_name:
            await client.indices.delete(index=current_index_name)


async def clean_test_indices(client: AsyncElasticsearch):
    """Delete all documents from all known indices after tests."""
    for index in indices:
        index_manager = IndexManager(index, client)
        current_index_name = await index_manager.get_current_index_name()
        await client.indices.refresh(index=current_index_name)
        await index_manager.client.delete_by_query(
            index=current_index_name,
            body={"query": {"match_all": {}}},
            conflicts="proceed",
        )
        await client.indices.refresh(index=current_index_name)
