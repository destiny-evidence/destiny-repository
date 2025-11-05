"""Index manager for an elasticsearch index."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import elasticsearch
from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import AsyncDocument
from opentelemetry import trace
from taskiq import AsyncTaskiqDecoratedTask

from app.core.exceptions import NotFoundError
from app.core.telemetry.attributes import (
    Attributes,
    name_span,
    set_span_status,
    trace_attribute,
)
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


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
        client: AsyncElasticsearch,
        *,
        otel_enabled: bool = False,
        repair_task: AsyncTaskiqDecoratedTask[..., Coroutine[Any, Any, None]]
        | None = None,
        version_prefix: str = "v",
        reindex_status_polling_interval: float = 5,
    ) -> None:
        """
        Initialize the migration manager.

        Args:
            document_class: The AsyncDocument subclass defining the mapping
            client: AsyncElasticsearch client
            repair_task: Asynchronous task used to repair an index (defaults None)
            version_prefix: Prefix for version numbers in index names
            reindex_status_polling_interval: How often to check status of reindexing (defaults 5s)

        """  # noqa: E501
        self.document_class = document_class
        self.client = client
        self.repair_task = repair_task
        self.version_prefix = version_prefix
        self.reindex_status_polling_interval = reindex_status_polling_interval

        self.alias_name = document_class.Index.name
        self.otel_enabled = otel_enabled

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
        except elasticsearch.NotFoundError:
            return None

    @tracer.start_as_current_span("Rebuild index")
    async def rebuild_index(self) -> None:
        """
        WARNING: DESTRUCTIVE ACTION.

        Rebuild the current index by deleting, recreating, and repopulating.
        """
        trace_attribute(
            attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=self.alias_name
        )
        current_index_name = await self.get_current_index_name()

        if not current_index_name:
            msg = f"Index with alias {self.alias_name} does not exist"
            set_span_status(status=trace.StatusCode.ERROR, detail=msg)
            raise NotFoundError(msg)

        name_span(f"Rebuild index - {current_index_name}")

        await self.client.indices.delete_alias(
            index=current_index_name, name=self.alias_name
        )

        logger.info("Destroying index", index=current_index_name)
        await self._delete_index_safely(index_name=current_index_name)

        logger.info("Recreating index", index=current_index_name)
        await self._create_index_with_mapping(current_index_name)

        await self.client.indices.put_alias(
            index=current_index_name, name=self.alias_name
        )

        await self.repair_index()

    @tracer.start_as_current_span("Repair index")
    async def repair_index(self) -> None:
        """Repair the current index."""
        trace_attribute(
            attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=self.alias_name
        )
        if not self.repair_task:
            msg = f"No index repair task found for {self.alias_name}"
            set_span_status(status=trace.StatusCode.ERROR, detail=msg)
            raise NotFoundError(msg)

        await queue_task_with_trace(self.repair_task, otel_enabled=self.otel_enabled)

    def _generate_index_name(self, version: int) -> str:
        """Generate a versioned index name."""
        return f"{self.alias_name}_{self.version_prefix}{version}"

    async def _create_index_with_mapping(self, index_name: str) -> None:
        """
        Create a new index with the mapping from the document class.

        Args:
            index_name: Name of the index to create

        """
        await self.document_class.init(index=index_name, using=self.client)
        logger.info("Created index: %s", index_name)

    @tracer.start_as_current_span("Initialize index")
    async def initialize_index(self) -> str:
        """
        Initialize the index with version 1 if it doesn't exist.

        Returns:
            The name of the active index

        """
        trace_attribute(
            attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=self.alias_name
        )

        current_index = await self.get_current_index_name()

        if current_index is None:
            index_name = self._generate_index_name(1)

            name_span(f"Initialize index {index_name}")

            await self._create_index_with_mapping(index_name)

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

    @tracer.start_as_current_span("Migrate index")
    async def migrate(self) -> str | None:
        """
        Migrate to a new index version.

        Returns:
            New index name if migration occurred, None otherwise

        """
        trace_attribute(
            attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=self.alias_name
        )

        source_index = await self.get_current_index_name()

        if source_index is None:
            logger.info("No existing index for %s, initialising", self.alias_name)
            return await self.initialize_index()

        # Currently required for backwards compatibility with our
        # existing index names.
        # TODO(Jack): Remove once all indices are versioned  # noqa: TD003
        current_version = await self.get_current_version(source_index)
        if current_version is None:
            msg = "Current index does not have a version, will use version 1."
            logger.info(msg)
            current_version = 0

        new_version = current_version + 1
        destination_index = self._generate_index_name(new_version)

        name_span(f"Migrate index {source_index} to {destination_index}")

        logger.info("Starting migration from %s to %s", source_index, destination_index)

        # Create the destination index
        await self._create_index_with_mapping(index_name=destination_index)

        # Reindex data
        await self._reindex_data(
            source_index=source_index, dest_index=destination_index
        )

        # Switch alias atomically,
        await self._switch_alias(source_index, destination_index)

        # Block writes to old index
        await self.client.indices.add_block(index=source_index, block="write")

        # Trigger a second reindex to top up
        await self._reindex_data(
            source_index=source_index, dest_index=destination_index
        )

        logger.info("Migration completed successfully to %s", destination_index)
        return destination_index

    @tracer.start_as_current_span("Reindexing index")
    async def _reindex_data(self, source_index: str, dest_index: str) -> None:
        """
        Reindex data from source to destination index.

        Args:
            source_index: Source index name
            dest_index: Destination index name

        """
        trace_attribute(
            attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=self.alias_name
        )

        name_span(f"Reindex {source_index} to {dest_index}")
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
            conflicts="proceed",
            source={"index": source_index},
            dest={"index": dest_index, "version_type": "external"},
            wait_for_completion=False,
            refresh=True,
        )

        # The task management API is in technical preview at time of writing
        # But has been in technical preview for four major versions.
        # So we're fine. Some nasty logs though.
        task = await self.client.tasks.get(task_id=response["task"])

        while not task["completed"]:
            progress = task["task"]["status"]["created"]
            +task["task"]["status"]["updated"]
            +task["task"]["status"]["version_conflicts"]

            logger.info(
                "Reindexing documents in progress: %s out of %s", progress, total_docs
            )

            await asyncio.sleep(self.reindex_status_polling_interval)
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
        try:
            alias_info = await self.client.indices.get_alias(index=index_name)
            if index_name in alias_info and alias_info[index_name]["aliases"]:
                logger.warning(
                    "Index %s still has aliases, skipping deletion", index_name
                )
                return
        except NotFoundError:
            pass

        await self.client.indices.delete(index=index_name)
        logger.info("Deleted old index: %s", index_name)

    @tracer.start_as_current_span("Rollback index")
    async def rollback(
        self, target_version: int | None = None, target_index: str | None = None
    ) -> str:
        """
        Rollback to a previous version or the previous version if not specified.

        Args:
            target_version: Version to rollback to (defaults to current - 1) OR
            target_index: for backwards compatibilitiy until all indices are renamed.

        Returns:
            The index name that was rolled back to

        Raises:
            NotFoundError: If there is no current index to roll back from
            NotFoundError: If the target index does not exist
            ValueError: If the target version is invalid (e.g. 0 or earlier)

        """
        trace_attribute(
            attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=self.alias_name
        )

        current_index = await self.get_current_index_name()

        if current_index is None:
            msg = "Cannot rollback: no current index found"
            set_span_status(status=trace.StatusCode.ERROR, detail=msg)
            raise NotFoundError(msg)

        current_version = await self.get_current_version(index_name=current_index)

        if current_version is None or (current_version == 1 and target_index is None):
            msg = "Cannot rollback: no previous version available"
            set_span_status(status=trace.StatusCode.ERROR, detail=msg)
            raise ValueError(msg)

        if target_index is None:
            if target_version is None:
                target_version = current_version - 1

            if target_version < 1:
                msg = "Cannot rollback: cannot target version of zero or earlier."
                set_span_status(status=trace.StatusCode.ERROR, detail=msg)
                raise ValueError(msg)

            target_index = self._generate_index_name(target_version)

        if not await self.client.indices.exists(index=target_index):
            msg = f"Target index {target_index} does not exist"
            set_span_status(status=trace.StatusCode.ERROR, detail=msg)
            raise NotFoundError(msg)

        name_span(f"Rollback index {current_index} to {target_index}")

        await self._switch_alias(current_index, target_index)

        logger.info("Rolled back from %s to %s", current_index, target_index)
        return target_index
