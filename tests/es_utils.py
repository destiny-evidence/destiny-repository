"""Utilities for managing Elasticsearch indices for tests."""

from elasticsearch import AsyncElasticsearch

from app.persistence.es.client import indices


async def create_test_indices(client: AsyncElasticsearch):
    """Create all indices needed for tests."""
    for index in indices:
        exists = await client.indices.exists(index=index.Index.name)
        if not exists:
            await index.init(using=client)


async def delete_test_indices(client: AsyncElasticsearch):
    """Delete all indices after tests."""
    for index in indices:
        exists = await client.indices.exists(index=index.Index.name)
        if exists:
            await client.indices.delete(index=index.Index.name)


async def clean_test_indices(client: AsyncElasticsearch):
    """Delete all documents from all indices after tests."""
    for index in indices:
        exists = await client.indices.exists(index=index.Index.name)
        if exists:
            await client.delete_by_query(
                index=index.Index.name, body={"query": {"match_all": {}}}
            )
