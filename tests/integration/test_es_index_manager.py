"""Tests for the elasticsearch index manager."""

from collections.abc import AsyncGenerator

import pytest

from app.core.exceptions import NotFoundError
from app.persistence.es.client import AsyncESClientManager
from app.persistence.es.index_manager import IndexManager
from tests.es_utils import DomainSimpleDoc, SimpleDoc, delete_test_indices


@pytest.fixture
async def index_manager(
    es_manager_for_tests: AsyncESClientManager,
) -> AsyncGenerator[IndexManager, None]:
    """
    Fixture for an index manager for the SimpleDoc.

    Cleans up its index at the end of of the test.
    """
    async with es_manager_for_tests.client() as client:
        await delete_test_indices(client)

        index_manager = IndexManager(
            SimpleDoc,
            client,
            reindex_status_polling_interval=1,
        )

        yield index_manager

        await delete_test_indices(client)


async def test_initialise_es_index_happy_path(index_manager: IndexManager):
    """Test that we can initialise an index for a GenericESPersistence."""
    # Assert that the index does not exist
    index_exists = await index_manager.client.indices.exists(index=SimpleDoc.Index.name)
    assert not index_exists

    # Initialise the index
    await index_manager.initialize_index(
        settings={
            "number_of_shards": 2,
            "search": {"slowlog": {"threshold": {"query": {"warn": "20s"}}}},
        }
    )

    # Check we've created a versioned index
    versioned_index_name = await index_manager.get_current_index_name()
    assert versioned_index_name
    versioned_index_exists = await index_manager.client.indices.exists(
        index=versioned_index_name
    )
    assert versioned_index_exists

    # Check that the correct alias has been applied
    assert SimpleDoc.Index.name == index_manager.alias_name
    alias_exists = await index_manager.client.indices.exists_alias(
        name=index_manager.alias_name, index=versioned_index_name
    )
    assert alias_exists

    # Assert that the current version is 1
    current_version = await index_manager.get_current_version()
    assert current_version == 1

    # Assert that the index has the correct number of shards
    assert await index_manager.get_current_number_of_shards() == 2


async def test_initialise_es_index_is_idempotent(index_manager: IndexManager):
    """Make sure that subsequent initialization calls have no impact."""
    await index_manager.initialize_index()

    # Get the current index name so we can verify it doesn't change
    index_name = await index_manager.get_current_index_name()

    # Add a document to the index so we can check for it
    # after reinitialising
    dummy_doc = SimpleDoc.from_domain(DomainSimpleDoc(content="test document"))
    doc_added = await dummy_doc.save(using=index_manager.client, validate=True)
    assert doc_added == "created"

    # Refresh the index to ensure document available
    await index_manager.client.indices.refresh(index=index_name)

    # Call the initialization again
    await index_manager.initialize_index(settings={"number_of_shards": 2})

    # Verify the current index name has not changed
    new_index_name = await index_manager.get_current_index_name()
    assert new_index_name == index_name

    # Assert the count of documents has not changed
    count = await index_manager.client.count(index=index_manager.alias_name)
    assert count["count"] == 1

    # Assert shard count has not changed
    assert await index_manager.get_current_number_of_shards() == 1


async def test_migrate_es_index_happy_path(index_manager: IndexManager):
    """Test that we can migrate an index and that settings are persisted."""
    # Initialise the index
    await index_manager.initialize_index(
        settings={
            "number_of_shards": 2,
            "search": {
                "slowlog": {"threshold": {"query": {"warn": "20s", "debug": "5s"}}}
            },
        }
    )

    # Add documents to index so we can check for them after migrating
    dummy_docs = [
        SimpleDoc.from_domain(DomainSimpleDoc(content=f"test document {i}"))
        for i in range(1, 11)
    ]

    for dummy_doc in dummy_docs:
        doc_added = await dummy_doc.save(using=index_manager.client, validate=True)
        assert doc_added == "created"

    # Refresh the index to ensure documents available
    await index_manager.client.indices.refresh(index=index_manager.alias_name)

    # Get current index name so we can verify it is deleted
    old_index_name = await index_manager.get_current_index_name()

    # Get current index version so we can verify it is incremented
    old_version = await index_manager.get_current_version()
    assert old_version

    await index_manager.migrate(
        settings_changeset={
            "search": {"slowlog": {"threshold": {"query": {"warn": "10s"}}}}
        }
    )

    # Verify the old index has not been deleted
    old_index_exists = await index_manager.client.indices.exists(index=old_index_name)
    assert old_index_exists

    # Verify the version is not None and has incremented
    new_version = await index_manager.get_current_version()
    assert new_version
    assert new_version == (old_version + 1)

    # Verify the index name has changed
    new_index_name = await index_manager.get_current_index_name()
    assert new_index_name == f"{index_manager.alias_name}_v{new_version}"

    # Verify the alias exists on the new index
    alias_exists = await index_manager.client.indices.exists_alias(
        index=new_index_name, name=index_manager.alias_name
    )
    assert alias_exists

    # Verify there are ten documents in the new index
    assert (await index_manager.client.count(index=new_index_name))["count"] == 10

    index_settings = (
        await index_manager.client.indices.get_settings(index=new_index_name)
    )[new_index_name]["settings"]["index"]

    # Verify the slowlog warn threshold has been set to 10s
    assert index_settings["search"]["slowlog"]["threshold"]["query"]["warn"] == "10s"

    # Verify the slowlog debug threshold has been preserved as 5s
    assert index_settings["search"]["slowlog"]["threshold"]["query"]["debug"] == "5s"

    # Verify the number of shards is still 2
    assert await index_manager.get_current_number_of_shards() == 2


async def test_we_can_migrate_an_index_with_a_random_name(index_manager: IndexManager):
    """Test we can migrate if alias points to non-versioned index name."""
    non_versioned_index_name = f"{SimpleDoc.Index.name}_forever"

    # Create non_versioned index and apply alias index manager will recognize
    await SimpleDoc.init(index=non_versioned_index_name, using=index_manager.client)
    await index_manager.client.indices.put_alias(
        index=non_versioned_index_name, name=SimpleDoc.Index.name
    )

    # Migrating should move us over to dummy_v1
    await index_manager.migrate()

    current_index_name = await index_manager.get_current_index_name()
    assert current_index_name
    assert current_index_name == f"{index_manager.alias_name}_v1"


async def test_migrate_es_index_updates_shards(index_manager: IndexManager):
    """Test that we can migrate an index and update the number of shards."""
    # Initialise the index
    await index_manager.initialize_index()

    # Migrate with different number of shards
    new_number_of_shards = 4
    await index_manager.migrate(
        settings_changeset={"number_of_shards": new_number_of_shards}
    )

    # Verify the new index has the correct number of shards
    assert await index_manager.get_current_number_of_shards() == new_number_of_shards


async def test_migrate_es_index_inherits_shards(index_manager: IndexManager):
    """Test that we can migrate an index and update the number of shards."""
    # Initialise the index
    await index_manager.initialize_index(settings={"number_of_shards": 2})

    # Migrate with no number of shards specified
    await index_manager.migrate()

    # Verify the new index has the correct number of shards
    assert await index_manager.get_current_number_of_shards() == 2


async def test_reindex_preserves_data_updated_in_source(index_manager: IndexManager):
    """
    Test that a second reindex captures updates from the source index.

    We're manufacturing an update on  a specific document id
    to confirm we can successfully reindex.

    This tests some internals of the index manager and verifies elasticsearch
    behavior.
    """
    await index_manager.initialize_index()

    src_index_name = await index_manager.get_current_index_name()
    assert src_index_name

    # Add a document to the  source index
    dummy = DomainSimpleDoc(content="test document")
    dummy_document_src = SimpleDoc.from_domain(dummy)

    doc_added = await dummy_document_src.save(using=index_manager.client, validate=True)
    assert doc_added == "created"

    # Refresh the index to ensure document available
    await index_manager.client.indices.refresh(index=src_index_name)

    # Create our destination index
    dest_index_name = f"{SimpleDoc.Index.name}_v2"
    await SimpleDoc.init(index=dest_index_name, using=index_manager.client)

    # Reindex from src to dest
    await index_manager._reindex_data(  # noqa: SLF001
        source_index=src_index_name, dest_index=dest_index_name
    )

    # Assert that document in destination index with version 1
    doc_from_index = await index_manager.client.get(
        index=index_manager.alias_name, id=dummy_document_src.meta.id
    )

    assert doc_from_index["found"]
    assert doc_from_index["_version"] == 1
    assert doc_from_index["_source"]["content"] == "test document"

    # Add an updated version of dummy to the _source_ index
    # After this we should have an updated document in the
    # source index with an elasticsearch version of 2
    # and the destination index will have the old document
    # with an elasticsearch version of 1
    dummy_document_src.content = "updated test document"
    doc_added = await dummy_document_src.save(
        index=src_index_name, using=index_manager.client, validate=True
    )

    # Refresh the index to ensure updated document available
    await index_manager.client.indices.refresh(index=src_index_name)

    # reindex
    await index_manager._reindex_data(  # noqa: SLF001
        source_index=src_index_name, dest_index=dest_index_name
    )

    # Assert that document in destination index with version 2
    doc_from_index = await index_manager.client.get(
        index=index_manager.alias_name, id=dummy_document_src.meta.id
    )

    assert doc_from_index["found"]
    assert doc_from_index["_version"] == 2
    assert doc_from_index["_source"]["content"] == "updated test document"


async def test_reindex_succeeds_on_version_clash(index_manager: IndexManager):
    """
    Test that a second reindex succeeds when there is a version clash on documents.

    We're manufacturing an clash on a specific document id
    to confirm we can successfully reindex. This is a (likely rare) edge case
    that could happen if:
    * Document is not present in src index during first reindex.
    * Document is added to src prior to second reindex.
    * Same document is added to dest after we switch the write over _before_
      it is added as part of the second reindex, and the document is different.

    In this case, we want to preserve the document in the destination index,
    as this will have been the most recently updated.

    This tests some internals of the index manager and verifies elasticsearch
    behavior.
    """
    await index_manager.initialize_index()

    src_index_name = await index_manager.get_current_index_name()
    assert src_index_name

    dummy = DomainSimpleDoc(content="test document")
    dummy_document_src = SimpleDoc.from_domain(dummy)

    doc_added = await dummy_document_src.save(using=index_manager.client, validate=True)
    assert doc_added == "created"

    # Refresh the index to ensure document available
    await index_manager.client.indices.refresh(index=src_index_name)

    # Assert that document in src index with version 1
    doc_from_src_index = await index_manager.client.get(
        index=src_index_name, id=str(dummy.id)
    )

    assert doc_from_src_index["found"]
    assert doc_from_src_index["_version"] == 1
    assert doc_from_src_index["_source"]["content"] == "test document"

    # Create the destination index
    dest_index_name = f"{SimpleDoc.Index.name}_v2"
    await SimpleDoc.init(index=dest_index_name, using=index_manager.client)

    # Update the content and save to the destination index
    dummy.content = "updated test document"
    dummy_document_dest = SimpleDoc.from_domain(dummy)
    doc_added = await dummy_document_dest.save(
        using=index_manager.client, index=dest_index_name
    )

    # Refresh the destination index to ensure document available
    await index_manager.client.indices.refresh(index=dest_index_name)

    # Assert that document in destination index with version 1
    # but with updated content
    doc_from_dest_index = await index_manager.client.get(
        index=dest_index_name, id=str(dummy.id)
    )
    assert doc_from_dest_index["found"]
    assert doc_from_dest_index["_version"] == 1
    assert doc_from_dest_index["_source"]["content"] == "updated test document"

    # reindex from src to dest
    await index_manager._reindex_data(  # noqa: SLF001
        source_index=src_index_name, dest_index=dest_index_name
    )

    # Assert that document in the destination index is unaffected.
    doc_from_dest_index = await index_manager.client.get(
        index=dest_index_name, id=str(dummy.id)
    )
    assert doc_from_dest_index["found"]
    assert doc_from_dest_index["_version"] == 1
    assert doc_from_dest_index["_source"]["content"] == "updated test document"


async def test_reindex_does_not_delete_documents_from_destination(
    index_manager: IndexManager,
):
    """Test that we do not delete documents from the dest index when reindexing."""
    await index_manager.initialize_index()

    # Get the current index name
    src_index_name = await index_manager.get_current_index_name()
    assert src_index_name

    # Immediately migrate to v2 index, not deleting the old index
    dest_index_name = await index_manager.migrate()
    assert dest_index_name

    # Add a document to the new index
    dummy = DomainSimpleDoc(content="test document")
    dummy_document_dest = SimpleDoc.from_domain(dummy)

    doc_added = await dummy_document_dest.save(
        using=index_manager.client, validate=True
    )
    assert doc_added == "created"

    # Refresh document to make available to search
    await index_manager.client.indices.refresh(index=dest_index_name)

    # Reindex from src to destination
    await index_manager._reindex_data(  # noqa: SLF001
        source_index=src_index_name, dest_index=dest_index_name
    )

    # Assert the dummy doc is present in the destination index
    doc_from_dest_index = await index_manager.client.get(
        index=dest_index_name, id=str(dummy.id)
    )
    assert doc_from_dest_index["found"]


async def test_rollback_to_previous_version(index_manager: IndexManager):
    """Test that we can roll back to the previous index version."""
    # Initialise the index
    await index_manager.initialize_index()

    # Migrate the index to the next version
    await index_manager.migrate()

    # Add a document to the new index to we can confirm is
    # is _not_ present after we roll back
    dummy_doc = SimpleDoc.from_domain(DomainSimpleDoc(content="test document"))
    doc_added = await dummy_doc.save(using=index_manager.client, validate=True)
    assert doc_added == "created"

    # Refresh the index to ensure document available
    await index_manager.client.indices.refresh(index=index_manager.alias_name)

    # Assert the count of documents in the migrated index is 1
    count = await index_manager.client.count(index=index_manager.alias_name)
    assert count["count"] == 1

    # Rollback to previous version
    await index_manager.rollback()

    # Assert the version is back to the previous version
    expect_v1 = await index_manager.get_current_version()
    assert expect_v1
    assert expect_v1 == 1

    # Assert no documents in index
    count = await index_manager.client.count(index=index_manager.alias_name)
    assert count["count"] == 0


async def test_rollback_to_previous_index_without_version(index_manager: IndexManager):
    """
    Required for backwards compatibiltiy until all indices renamed.

    We need to be able to roll back to a target index with a name that
    does not match our versioning pattern.
    """
    # Create an old index
    non_versioned_index_name = f"{SimpleDoc.Index.name}_forever"

    # Create non_versioned index
    await SimpleDoc.init(index=non_versioned_index_name, using=index_manager.client)

    # Initialise a v1 index with correct alias
    await index_manager.initialize_index()

    # Rollback targeting the non versioned index
    await index_manager.rollback(target_index=non_versioned_index_name)

    # Verify the alias has been moved to the non versioned index
    assert await index_manager.client.indices.exists_alias(
        name=SimpleDoc.Index.name, index=non_versioned_index_name
    )


async def test_we_do_not_to_roll_back_from_version_1(index_manager: IndexManager):
    """Test that we do not roll back if the current version is version one."""
    # Initialise the index to version 1
    await index_manager.initialize_index()

    # Immediately try to roll back to version 0
    with pytest.raises(ValueError, match="no previous version available"):
        await index_manager.rollback()


async def test_we_do_not_roll_back_past_version_one_from_later_versions(
    index_manager: IndexManager,
):
    """Test that we do not allow rollbacks past version 1."""
    # Initialise the index to version 1
    await index_manager.initialize_index()

    # Immediately migrate to v2
    await index_manager.migrate()

    # Try to roll back two versions to zero
    with pytest.raises(ValueError, match="cannot target version of zero or earlier"):
        await index_manager.rollback(target_version=0)


async def test_we_do_not_roll_back_to_nonexistent_index(index_manager: IndexManager):
    """Test that we do not roll back to an index that doesn't exist."""
    # Initialise the index to version 1
    await index_manager.initialize_index()

    # Get the current index name
    current_index = await index_manager.get_current_index_name()
    assert current_index

    # Immediately migrate to v2
    await index_manager.migrate()

    # Delete the old index
    await index_manager._delete_index_safely(index_name=current_index)  # noqa: SLF001

    # Try to roll back two versions to zero
    with pytest.raises(
        NotFoundError, match=f"Target index {SimpleDoc.Index.name}_v1 does not exist"
    ):
        await index_manager.rollback()
