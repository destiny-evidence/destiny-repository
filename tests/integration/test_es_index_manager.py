"""Tests for the elasticsearch index manager."""

from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import (
    Keyword,
    mapped_field,
)
from pydantic import Field

from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.persistence.es.index_manager import IndexManager
from app.persistence.es.persistence import GenericESPersistence


class Dummy(DomainBaseModel, SQLAttributeMixin):
    """
    A Dummy model to use for ES index manager tests.

    Uses the SQLAttributeMixin to autogenerate ids.
    Contains only an id and a note.
    """

    note: str = Field(description="some text for the tests.")


class DummyDocument(
    GenericESPersistence[Dummy],
):
    """Persistence model for Dummy in elasticsearch."""

    note: str = mapped_field(Keyword(required=True))

    class Index:
        """Index metadata for the persistence model."""

        name = "dummy"


async def test_initialise_es_index_happy_path(es_client: AsyncElasticsearch):
    """Test that we can initalise an index for a GenericESPersistence."""
    index_exists = await es_client.indices.exists(index=DummyDocument.Index.name)
    assert not index_exists

    index_manager = IndexManager(
        document_class=DummyDocument,
        alias_name=DummyDocument.Index.name,
        client=es_client,
    )

    await index_manager.initialize_index()

    # Check we've created a versioned index
    versioned_index_name = await index_manager.get_current_index_name()
    versioned_index_exists = await es_client.indices.exists(index=versioned_index_name)
    assert versioned_index_exists

    # Check that the correct alias has been applied
    assert DummyDocument.Index.name == index_manager.alias_name
    alias_exists = await es_client.indices.exists_alias(
        name=index_manager.alias_name, index=versioned_index_name
    )
    assert alias_exists

    # Clean up - remove this later, should be done elsewhere
    await index_manager.delete_current_index_unsafe()
