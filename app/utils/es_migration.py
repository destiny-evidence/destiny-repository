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


async def run_migration(indices: list[str], operation: str) -> None:
    """Run elasticsearch index migrations."""
    es_config = get_settings().es_config

    await es_manager.init(es_config)

    async with es_manager.client() as client:
        for index_name in indices:
            document_class = INDICES[index_name]
            manager = IndexManager(document_class, index_name, client)
            if operation == "migrate":
                # If the index does not exist, migrating will create it.
                await manager.migrate(delete_old=False)
            elif operation == "rollback":
                await manager.rollback()

    await es_manager.close()


def argument_parser() -> argparse.ArgumentParser:
    """Create argument parser for migrating indicies."""
    parser = argparse.ArgumentParser(description="Migrate elasticsearch indicies.")

    parser.add_argument(
        "-i",
        "--index",
        type=str,
        choices=[*INDICES, "all"],
        help="Name of the index to mgirate, or 'all' to migrate all indices.",
        required=True,
    )

    parser.add_argument(
        "-o",
        "--operation",
        type=str,
        choices=["migrate", "rollback"],
        help="Whether to migrate the index forward or roll back to a previous index.",
        required=True,
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    indices = [*INDICES] if args.index == "all" else [args.index]

    asyncio.run(run_migration(indices=indices, operation=args.operation))
