"""Utilities for managing Elasticsearch indices for tests."""

from typing import Self

from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import Integer, Text, mapped_field

from app.domain.base import SQLAttributeMixin
from app.persistence.es.index_manager import IndexManager
from app.persistence.es.persistence import GenericESPersistence
from app.system.routes import index_managers


class DomainSimpleDoc(SQLAttributeMixin):
    """Simple domain document with basic fields."""

    title: str = "Test title"
    year: int = 2025
    content: str = "Sample content"


class SimpleDoc(GenericESPersistence):
    """Simple test document with basic fields."""

    title: str = mapped_field(Text())
    year: int = mapped_field(Integer())
    content: str = mapped_field(Text())

    class Index:
        """Index metadata for the simple document."""

        name = "test_simple"

    def to_domain(self) -> DomainSimpleDoc:
        """Convert to simple domain dict."""
        return DomainSimpleDoc(
            id=self.meta.id,
            title=self.title,
            year=self.year,
            content=self.content,
        )

    @classmethod
    def from_domain(cls, domain_model: DomainSimpleDoc) -> Self:
        """Create from simple domain dict."""
        return cls(
            meta={"id": domain_model.id},  # type: ignore[call-arg]
            title=domain_model.title,
            year=domain_model.year,
            content=domain_model.content,
        )


def simple_doc_index_manager(es_client: AsyncElasticsearch) -> IndexManager:
    """Create an index manager for the reference index."""
    return IndexManager(
        document_class=SimpleDoc,
        client=es_client,
    )


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
