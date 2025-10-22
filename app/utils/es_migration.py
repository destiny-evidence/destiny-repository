"""Elasticsearch migration."""

import argparse
import asyncio

from app.core.config import get_settings
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.persistence.es.client import es_manager
from app.persistence.es.index_manager import IndexManager

# Indices mapping of name to document
INDICES = {
    ReferenceDocument.Index.name: ReferenceDocument,
    RobotAutomationPercolationDocument.Index.name: RobotAutomationPercolationDocument,
}


async def run_migration(alias: str) -> None:
    """Run elasticsearch index migrations."""
    es_config = get_settings().es_config

    await es_manager.init(es_config)

    async with es_manager.client() as client:
        document_class = INDICES[alias]
        manager = IndexManager(document_class, client)

        await manager.migrate(delete_old=False)

    await es_manager.close()


async def run_rollback(alias: str, target_index: str | None = None) -> None:
    """Roll back to the previous index, or the target."""
    es_config = get_settings().es_config

    await es_manager.init(es_config)

    async with es_manager.client() as client:
        document_class = INDICES[alias]
        manager = IndexManager(document_class, client)

        await manager.rollback(target_index=target_index)

    await es_manager.close()


def argument_parser() -> argparse.ArgumentParser:
    """Create argument parser for migrating indicies."""
    parser = argparse.ArgumentParser(description="Migrate or roll back an ES index.")

    parser.add_argument(
        "-i",
        "--index",
        type=str,
        choices=[*INDICES, "all"],
        help="Name of the index.",
        required=True,
    )

    parser.add_argument(
        "-m",
        "--migrate",
        action="store_true",
        help="Migrate the index",
        required=False,
    )

    parser.add_argument(
        "-r",
        "--rollback",
        action="store_true",
        help="Rollback the index",
        required=False,
    )

    parser.add_argument(
        "-t",
        "--target-index",
        type=str,
        help="Optional param to roll back to a target index name.",
        required=False,
        default=None,
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    indices = [*INDICES] if args.index == "all" else [args.index]

    if len(indices) > 1 and args.target_index:
        msg = "Can only specify target_index when rolling back a single index."
        raise RuntimeError(msg)

    if args.migrate:
        for index in indices:
            asyncio.run(run_migration(alias=index))

    elif args.rollback:
        for index in indices:
            asyncio.run(run_rollback(alias=index, target_index=args.target_index))
