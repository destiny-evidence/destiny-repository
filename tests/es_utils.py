"""Utilities for managing Elasticsearch indices for tests."""

import uuid

from elasticsearch import AsyncElasticsearch

from app.persistence.es.client import indices

TEST_INDEX_SUFFIX = f"_test_{uuid.uuid4().hex[:8]}"


def patch_index_names():
    """Patch index names to use test-specific suffix."""
    for index in indices:
        index.Index.name += TEST_INDEX_SUFFIX


async def create_test_indices(client: AsyncElasticsearch):
    """Create all indices needed for tests."""
    patch_index_names()
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
