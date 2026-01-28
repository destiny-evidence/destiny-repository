"""Elasticsearch migration."""

import argparse
import asyncio

from elasticsearch import NotFoundError
from opentelemetry import trace

from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger, logger_configurer
from app.core.telemetry.otel import configure_otel
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.persistence.es.client import es_manager
from app.persistence.es.index_manager import IndexManager
from app.utils.es.config import get_settings as get_es_migration_settings

settings = get_es_migration_settings()
logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

logger_configurer.configure_console_logger(
    log_level=settings.log_level, rich_rendering=settings.running_locally
)

if settings.otel_config and settings.otel_enabled:
    configure_otel(
        settings.otel_config,
        settings.app_name,
        settings.toml.app_version,
        settings.env,
    )

index_documents = {
    ReferenceDocument.Index.name: ReferenceDocument,
    RobotAutomationPercolationDocument.Index.name: RobotAutomationPercolationDocument,
}


async def run_migration(alias: str, number_of_shards: int | None) -> None:
    """Run elasticsearch index migrations."""
    es_config = settings.es_config

    await es_manager.init(es_config)

    try:
        async with es_manager.client() as client:
            index_manager = IndexManager(
                document_class=index_documents[alias],
                client=client,
                otel_enabled=settings.otel_enabled,
                reindex_status_polling_interval=settings.reindex_status_polling_interval,
                number_of_shards=number_of_shards,
            )
            await index_manager.migrate()
    except Exception:
        logger.exception("An unhandled exception occurred")
    finally:
        await es_manager.close()


async def run_rollback(alias: str, target_index: str | None = None) -> None:
    """Roll back to the previous index, or the target."""
    es_config = settings.es_config

    await es_manager.init(es_config)

    try:
        async with es_manager.client() as client:
            index_manager = IndexManager(
                document_class=index_documents[alias],
                client=client,
                otel_enabled=settings.otel_enabled,
            )
            if target_index:
                await index_manager.rollback(target_index=target_index)
            else:
                await index_manager.rollback()
    except Exception:
        logger.exception("An unhandled exception occurred")
    finally:
        await es_manager.close()


@tracer.start_as_current_span("Delete index")
async def delete_old_index(index_to_delete: str) -> None:
    """
    Delete an index after checking it is not in use.

    We implement this here instead of the index manager as
    this is entirely a cleanup step and not linked to a document_class.
    """
    trace_attribute(
        attribute=Attributes.DB_COLLECTION_ALIAS_NAME, value=index_to_delete
    )
    es_config = settings.es_config

    await es_manager.init(es_config)

    try:
        async with es_manager.client() as client:
            try:
                alias_info = await client.indices.get_alias(index=index_to_delete)
                if (
                    index_to_delete in alias_info
                    and alias_info[index_to_delete]["aliases"]
                ):
                    logger.warning(
                        "Index %s still has aliases, skipping deletion", index_to_delete
                    )
                    return
            except NotFoundError:
                pass

            await client.indices.delete(index=index_to_delete)
            logger.info("Deleted old index: %s", index_to_delete)
    except Exception:
        logger.exception("An unhandled exception occurred")
    finally:
        await es_manager.close()


def argument_parser() -> argparse.ArgumentParser:
    """Create argument parser for migrating indices."""
    parser = argparse.ArgumentParser(description="Migrate or roll back an ES index.")

    operation_group = parser.add_mutually_exclusive_group(required=True)

    operation_group.add_argument(
        "-m",
        "--migrate",
        action="store_true",
        help="Migrate the index.",
    )

    operation_group.add_argument(
        "-r",
        "--rollback",
        action="store_true",
        help="Rollback the index.",
    )

    operation_group.add_argument(
        "-d",
        "--delete",
        action="store_true",
        help="Delete an index after first verifying it is not in use.",
    )

    parser.add_argument(
        "-a",
        "--alias",
        type=str,
        choices=[*index_documents.keys(), "all"],
        help="Alias of the index to migrate.",
    )

    parser.add_argument(
        "-t",
        "--target-index",
        type=str,
        help="Optional param to roll back to or delete a target index name.",
        default=None,
    )

    parser.add_argument(
        "-n",
        "--number-of-shards",
        type=int,
        help=(
            "Number of shards to use when migrating an index. "
            "Defaults to the previous index's number of shards if not specified."
        ),
    )

    return parser


def validate_args(args: argparse.Namespace) -> None:
    """
    Enforce specific argument combinations, raising RuntimeError if violated.

    Due to the mutually exclusive parsing group, we're guaranteed a single operation
    but we need to check that valid arguments have been passed:

    * Migrating an index requires an index alias, or all.
    * Rolling back requires an index alias, and may have a target index name
    * Deleting requires a target index name.

    We should be able to massively simplify this once we've migrated existing
    indices to the versioned pattern, as the checks become:

    * Migrating and Rolling back an index require an alias
    * Deleting requires a target index name.

    So we can use a mutually exclusive group for --alias and --target-index
    and simplify below checks.
    """
    if args.migrate and (not args.alias or args.target_index):
        msg = (
            "You cannot specify a target index when migrating an index."
            "Please use --alias instead."
        )

    if args.rollback and args.alias == "all" and args.target_index:
        msg = (
            "You can only specify target_index when rolling back a single index."
            "Please either remove --target-index or choose a single --alias."
        )
        raise RuntimeError(msg)

    if args.delete and (not args.target_index or args.alias):
        msg = (
            "You must specify a full target index name and not an alias "
            "when deleting an index. "
            "Please use --target-index to target index for deletion."
        )
        raise RuntimeError(msg)

    if args.number_of_shards and not args.migrate:
        msg = "You can only specify number_of_shards when migrating an index."
        raise RuntimeError(msg)


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    validate_args(args)

    if args.delete:
        asyncio.run(delete_old_index(index_to_delete=args.target_index))

    aliases = [*index_documents.keys()] if args.alias == "all" else [args.alias]

    if args.migrate:
        for alias in aliases:
            asyncio.run(
                run_migration(alias=alias, number_of_shards=args.number_of_shards)
            )

    elif args.rollback:
        for alias in aliases:
            asyncio.run(run_rollback(alias=alias, target_index=args.target_index))
