"""Index manager for an elasticsearch index."""

import asyncio
from collections.abc import Coroutine
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.dsl import AsyncDocument
from taskiq import AsyncTaskiqDecoratedTask

from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace

logger = get_logger(__name__)


class IndexManager:
    """
    Manages an elasticsearch index.

    Including migrations with versioning and zero-downtime upgrades.

    Uses an alias to point to the current active index version, allowing seamless
    migrations by creating new indices and switching the alias atomically.
    """

    def __init__(  # noqa: PLR0913
        self,
        document_class: type[AsyncDocument],
        alias_name: str,
        client: AsyncElasticsearch,
        repair_task: AsyncTaskiqDecoratedTask[..., Coroutine[Any, Any, None]]
        | None = None,
        version_prefix: str = "v",
        batch_size: int = 1000,
    ) -> None:
        """
        Initialize the migration manager.

        Args:
            document_class: The AsyncDocument subclass defining the mapping
            alias_name: The alias name (defaults to document_class._index._name)
            client: AsyncElasticsearch client
            repair_task: Asynchronous task used to repair an index (defaults None)
            version_prefix: Prefix for version numbers in index names
            batch_size: Batch size for reindexing operations

        """
        self.document_class = document_class
        self.client = client
        self.repair_task = repair_task
        self.batch_size = batch_size
        self.version_prefix = version_prefix

        self.base_index_name = document_class.Index.name
        self.alias_name = alias_name or self.base_index_name

    async def get_current_version(self, index_name: str | None = None) -> int | None:
        """
        Get the current version number of the index pointed to by the alias.

        Returns:
            Current version number or None if alias doesn't exist

        """
        current_index_name = index_name or await self.get_current_index_name()
        if current_index_name is None:
            return None
        try:
            version_str = current_index_name.split(f"_{self.version_prefix}")[-1]
            return int(version_str)
        except ValueError:
            logger.warning(
                "Could not parse version from index name: %s", current_index_name
            )
            return None

    async def get_current_index_name(self) -> str | None:
        """
        Get the name of the current index pointed to by the alias.

        Returns:
            Current index name or None if alias doesn't exist

        """
        try:
            alias_info = await self.client.indices.get_alias(name=self.alias_name)
            indices = list(alias_info.keys())
            return indices[0] if indices else None
        except NotFoundError:
            return None

    async def rebuild_index(self) -> None:
        """
        Rebuild the current index.

        Delete and then recreate the index with the same name.
        This is used by the system router to trigger downtime rebuilds of indices.
        """
        current_index_name = await self.get_current_index_name()

        if not current_index_name:
            msg = f"Index with alias {self.alias_name} has not been initialized."
            raise NotFoundError(msg)

        # Remove the alias
        await self.client.indices.delete_alias(
            index=current_index_name, name=self.alias_name
        )

        logger.info("Destroying index", index=current_index_name)
        await self._delete_index_safely(index_name=current_index_name)

        logger.info("Recreating index", index=current_index_name)
        await self._create_index_with_mapping(current_index_name)

        # Reapply alias
        await self.client.indices.put_alias(
            index=current_index_name, name=self.alias_name
        )

    async def repair_index(self) -> None:
        """Repair the current index."""
        if not self.repair_task:
            msg = f"No index repair task found for {self.alias_name}"
            raise NotFoundError(msg)
        await queue_task_with_trace(self.repair_task)

    async def refresh_index(self) -> None:
        """Refresh the index."""
        current_index_name = await self.get_current_index_name()
        if not current_index_name:
            msg = f"Index with alias {self.alias_name} has not been initialized."
            raise NotFoundError(msg)
        await self.client.indices.refresh(index=current_index_name)

    def _generate_index_name(self, version: int) -> str:
        """Generate a versioned index name."""
        return f"{self.base_index_name}_{self.version_prefix}{version}"

    async def _create_index_with_mapping(self, index_name: str) -> None:
        """
        Create a new index with the mapping from the document class.

        Args:
            index_name: Name of the index to create

        """
        await self.document_class.init(index=index_name, using=self.client)
        logger.info("Created index: %s", index_name)

    async def initialize_index(self) -> str:
        """
        Initialize the index with version 1 if it doesn't exist.

        Returns:
            The name of the active index

        """
        current_index = await self.get_current_index_name()

        if current_index is None:
            # First time setup
            index_name = self._generate_index_name(1)

            # Create the index
            await self._create_index_with_mapping(index_name)

            # Create the alias
            await self.client.indices.put_alias(index=index_name, name=self.alias_name)

            logger.info(
                "Initialized index system with %s -> %s",
                index_name,
                self.alias_name,
            )
            return index_name
        logger.info(
            "Index system already initialized: %s -> %s",
            current_index,
            self.alias_name,
        )
        return current_index

    async def migrate(
        self,
        *,
        delete_old: bool = False,
    ) -> str | None:
        """
        Migrate to a new index version.

        Args:
            delete_old: Delete the old index after successful migration

        Returns:
            New index name if migration occurred, None otherwise

        """
        current_index = await self.get_current_index_name()

        if current_index is None:
            logger.info("No existing index for %s, initialising", self.alias_name)
            return await self.initialize_index()

        # Currently required for backwards compatibility with our
        # existing index names.
        # TODO(Jack): Remove once all indices are versioned  # noqa: TD003
        current_version = await self.get_current_version(current_index)
        if current_version is None:
            msg = "Current index does not have a version, will use version 1."
            logger.info(msg)
            current_version = 0

        # Create new versioned index
        new_version = current_version + 1
        new_index = self._generate_index_name(new_version)

        logger.info("Starting migration from %s to %s", current_index, new_index)

        # Create new index
        await self._create_index_with_mapping(index_name=new_index)

        # Reindex data
        await self._reindex_data(source_index=current_index, dest_index=new_index)

        # Switch alias atomically
        await self._switch_alias(current_index, new_index)

        # Delete old index if requested
        if delete_old:
            await self._delete_index_safely(current_index)

        logger.info("Migration completed successfully to %s", new_index)
        return new_index

    async def _reindex_data(self, source_index: str, dest_index: str) -> None:
        """
        Reindex data from source to destination index.

        Args:
            source_index: Source index name
            dest_index: Destination index name

        """
        logger.info("Reindexing from %s to %s", source_index, dest_index)

        # Get document count for progress tracking
        count_response = await self.client.count(index=source_index)
        total_docs = count_response["count"]

        if total_docs == 0:
            logger.info("No documents to reindex")
            return

        logger.info("Reindexing %s documents...", total_docs)

        # Trigger a reindex task
        response = await self.client.reindex(
            source={"index": source_index, "size": self.batch_size},
            dest={"index": dest_index},
            wait_for_completion=False,
            refresh=True,
        )

        # The task management API is in technical previewn at time of writing
        # But has been in technical preview for four major versions.
        # So we're probably fine. Some nasty logs though.
        # TODO(Jack): not ugly polling.  # noqa: TD003
        task = await self.client.tasks.get(task_id=response["task"])
        while not task["completed"]:
            await asyncio.sleep(5)  # Configure this
            task = await self.client.tasks.get(task_id=response["task"])

        logger.info(
            "Reindexed %s documents in %s ms",
            task["response"]["total"],
            task["response"]["took"],
        )

    async def _switch_alias(self, old_index: str, new_index: str) -> None:
        """
        Atomically switch the alias from old to new index.

        Args:
            old_index: Current index name
            new_index: New index name

        """
        actions = [
            {"remove": {"index": old_index, "alias": self.alias_name}},
            {"add": {"index": new_index, "alias": self.alias_name}},
        ]

        await self.client.indices.update_aliases(body={"actions": actions})
        logger.info(
            "Switched alias %s from %s to %s", self.alias_name, old_index, new_index
        )

    async def _delete_index_safely(self, index_name: str) -> None:
        """
        Safely delete an index after confirming it's not in use.

        Args:
            index_name: Name of index to delete

        """
        # Check if index has any aliases
        try:
            alias_info = await self.client.indices.get_alias(index=index_name)
            if index_name in alias_info and alias_info[index_name]["aliases"]:
                logger.warning(
                    "Index %s still has aliases, skipping deletion", index_name
                )
                return
        except NotFoundError:
            pass

        # Delete the index
        await self.client.indices.delete(index=index_name)
        logger.info("Deleted old index: %s", index_name)

    async def rollback(self, target_version: int | None = None) -> str:
        """
        Rollback to a previous version or the previous version if not specified.

        Args:
            target_version: Version to rollback to (defaults to current - 1)

        Returns:
            The index name that was rolled back to

        Raises:
            ValueError: If target version doesn't exist
            ValueError: If the target version is invalid (e.g. 0 or earlier)

        """
        current_index = await self.get_current_index_name()
        if current_index is None:
            msg = "Cannot rollback: no current index found"
            raise ValueError(msg)

        current_version = await self.get_current_version(index_name=current_index)

        if current_version is None or current_version == 1:
            msg = "Cannot rollback: no previous version available"
            raise ValueError(msg)

        if target_version is None:
            target_version = current_version - 1

        if target_version < 1:
            msg = "Cannot rollback: cannot target version of zero or earlier."
            raise ValueError(msg)

        target_index = self._generate_index_name(target_version)

        # Check if target index exists
        if not await self.client.indices.exists(index=target_index):
            msg = f"Target index {target_index} does not exist"
            raise ValueError(msg)

        # Switch alias back
        await self._switch_alias(current_index, target_index)

        logger.info("Rolled back from %s to %s", current_index, target_index)
        return target_index

    async def get_migration_history(self) -> dict[str, Any]:
        """
        Get information about all versions of the index.

        Returns:
            Dictionary with migration history information

        """
        pattern = f"{self.base_index_name}_{self.version_prefix}*"
        indices_info = await self.client.indices.get(index=pattern)

        history = {}
        current_index = await self.get_current_index_name()

        for index_name, info in indices_info.items():
            version_str = index_name.split(f"_{self.version_prefix}")[-1]
            try:
                version = int(version_str)
                count_response = await self.client.count(index=index_name)

                history[index_name] = {
                    "version": version,
                    "is_current": index_name == current_index,
                    "created": info["settings"]["index"]["creation_date"],
                    "document_count": count_response["count"],
                    "size_in_bytes": info.get("settings", {})
                    .get("index", {})
                    .get("size_in_bytes"),
                }
            except ValueError:
                continue

        return history
