"""Tests for the elasticsearch index manager."""

from collections.abc import AsyncGenerator
from typing import Self

import pytest
from elasticsearch.dsl import (
    Keyword,
    mapped_field,
)
from pydantic import Field

from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.persistence.es.client import AsyncESClientManager
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

    class Meta:
        """Allow unmapped fields in the document."""

        dynamic = True

    @classmethod
    def from_domain(cls, domain_obj: Dummy) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            meta={"id": str(domain_obj.id)},  # type: ignore[call-arg]
            note=domain_obj.note,
        )

    def to_domain(self) -> Dummy:
        """Create a domain model from this persistence model."""
        return Dummy(id=self.meta.id, note=self.note)


@pytest.fixture
async def index_manager(
    es_manager_for_tests: AsyncESClientManager,
) -> AsyncGenerator[IndexManager, None]:
    """
    Fixture for an index manager for the DummyDocument.

    Cleans up its index at the end of of the test.
    """
    async with es_manager_for_tests.client() as client:
        index_manager = IndexManager(DummyDocument, DummyDocument.Index.name, client)

        # Cleanup any hanging index
        await index_manager.delete_current_index_unsafe()

        yield index_manager

        await index_manager.delete_current_index_unsafe()


async def test_initialise_es_index_happy_path(index_manager: IndexManager):
    """Test that we can initalise an index for a GenericESPersistence."""
    # Assert that the index does not exist
    index_exists = await index_manager.client.indices.exists(
        index=DummyDocument.Index.name
    )
    assert not index_exists

    # Initialise the index
    await index_manager.initialize_index()

    # Check we've created a versioned index
    versioned_index_name = await index_manager.get_current_index_name()
    versioned_index_exists = await index_manager.client.indices.exists(
        index=versioned_index_name
    )
    assert versioned_index_exists

    # Check that the correct alias has been applied
    assert DummyDocument.Index.name == index_manager.alias_name
    alias_exists = await index_manager.client.indices.exists_alias(
        name=index_manager.alias_name, index=versioned_index_name
    )
    assert alias_exists

    # Assert that the current version is 1
    current_version = await index_manager.get_current_version()
    assert current_version == 1


async def test_initialise_es_index_is_idempotent(index_manager: IndexManager):
    """Make sure that subsequent intialisation calls have no impact."""
    await index_manager.initialize_index()

    # Get the current index name so we can verify it doesn't change
    index_name = await index_manager.get_current_index_name()

    # Add a document to the index so we can check for it
    # after reinitialising
    dummy_doc = DummyDocument.from_domain(Dummy(note="test document"))
    doc_added = await dummy_doc.save(using=index_manager.client, validate=True)
    assert doc_added == "created"

    # Refresh the index to ensure document available
    await index_manager.client.indices.refresh(index=index_manager.alias_name)

    # Call the initialisation again
    await index_manager.initialize_index()

    # Verify the current index name has not changed
    new_index_name = await index_manager.get_current_index_name()
    assert new_index_name == index_name

    # Assert the count of documents has not changed
    count = await index_manager.client.count(index=index_manager.alias_name)
    assert count["count"] == 1


async def test_migrate_es_index_happy_path(index_manager: IndexManager):
    """Test that we can migrate an index."""
    # Initialise the index
    await index_manager.initialize_index()

    # Add a document to the index so we can check for it
    # after reinitialising
    dummy_doc = DummyDocument.from_domain(Dummy(note="test document"))
    doc_added = await dummy_doc.save(using=index_manager.client, validate=True)
    assert doc_added == "created"

    # Refresh the index to ensure document available
    await index_manager.client.indices.refresh(index=index_manager.alias_name)

    # Get current index name so we can verify it is deleted
    old_index_name = await index_manager.get_current_index_name()

    # Get current index version so we can verify it is incremented
    old_version = await index_manager.get_current_version()
    assert old_version

    await index_manager.migrate(delete_old=True)

    # Verify the old index has been deleted
    old_index_exists = await index_manager.client.indices.exists(index=old_index_name)
    assert not old_index_exists

    # Verify the version is not None and has incremented
    new_version = await index_manager.get_current_version()
    assert new_version
    assert new_version == (old_version + 1)

    # Verify the index name has changed
    new_index_name = await index_manager.get_current_index_name()
    assert new_index_name == f"{index_manager.alias_name}_v2"

    # Verify the alias exists on the new index
    alias_exists = await index_manager.client.indices.exists_alias(
        index=new_index_name, name=index_manager.alias_name
    )
    assert alias_exists

    # Verify the document is in new index
    doc_from_index = await index_manager.client.get(
        index=index_manager.alias_name, id=dummy_doc.meta.id
    )
    assert doc_from_index["found"]


async def test_old_index_not_deleted_if_flag_unset(index_manager: IndexManager):
    """Test that we can leave the old index."""
    # Initialise the index
    await index_manager.initialize_index()

    # Get current index name so we can verify it is still there
    old_index_name = await index_manager.get_current_index_name()

    # Call without delete_old flag
    await index_manager.migrate()

    old_index_exists = await index_manager.client.indices.exists(index=old_index_name)
    assert old_index_exists

    # Now delete it
    await index_manager.client.indices.delete(index=old_index_name)

    old_index_exists = await index_manager.client.indices.exists(index=old_index_name)
    assert not old_index_exists
