"""
Drive a read-only deduplication evaluation over a supplied JSONL blob.

Connects to the environment's existing Postgres, Elasticsearch and blob storage,
assesses every record of the input against the live corpus, and writes the run's
artifact bundle back to blob storage. Postgres refuses a write from the run's
transactions; on Elasticsearch the guarantee is only that the assembled services
take read paths, so it is weaker.

```
uv run python -m app.run_evaluation \
    --input minio://operations/retrieval-query-set/v1/queries.jsonl \
    --dataset-version retrieval-query-set/v1 \
    --corpus-observed-at 2026-08-17T00:00:00+00:00 \
    --code-commit "$(git rev-parse HEAD)" \
    --pair-scorer my_package.my_module:build_scorer
```

Every run mints its own identifier, so a bundle is never overwritten. The run
holds no session between records, so it can be interrupted: the runner uploads
the record results it already has before the interrupt propagates.
"""

import argparse
import asyncio
import datetime
import importlib
from uuid import uuid7

from sqlalchemy import text

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger, logger_configurer
from app.core.telemetry.otel import configure_otel
from app.domain.references.models.models import (
    CandidateSelectionInput,
    DeduplicationAssessment,
    Reference,
    RetrievalPolicyName,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_assessment_service import (
    DeduplicationAssessmentService,
    PairScorer,
)
from app.domain.references.services.deduplication_evaluation_runner import (
    DeduplicationEvaluationRunner,
    EvaluationRunArtifacts,
    EvaluationRunConfiguration,
)
from app.domain.references.services.deduplication_service import DeduplicationService
from app.persistence.blob.models import BlobStorageFile
from app.persistence.blob.repository import BlobRepository, close_blob_clients
from app.persistence.es.client import es_manager
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.session import db_manager
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger = get_logger(__name__)

logger_configurer.configure_console_logger(
    log_level=settings.log_level, rich_rendering=settings.running_locally
)

if settings.otel_config and settings.otel_enabled:
    configure_otel(
        settings.otel_config,
        settings.app_name,
        settings.toml.app_version,
        settings.env,
        settings.trace_repr,
    )

# Distinguishes the run in pg_stat_activity from the API and worker traffic it
# shares a database with.
APPLICATION_NAME = "dedup-evaluation"


class EvaluationAssessor:
    """Assess one supplied record per read-only session against the live corpus."""

    def __init__(
        self, *, blob_repository: BlobRepository, pair_scorer: PairScorer
    ) -> None:
        """Keep the dependencies shared by every record."""
        self._blob_repository = blob_repository
        self._pair_scorer = pair_scorer

    async def evaluate_supplied(
        self,
        incoming: Reference,
        selection_input: CandidateSelectionInput,
        *,
        retrieval_policy: RetrievalPolicyName | None = None,
        k: int | None = None,
    ) -> DeduplicationAssessment:
        """Assess one record, holding a session no longer than that record."""
        async with db_manager.session() as session, es_manager.client() as client:
            sql_uow = AsyncSqlUnitOfWork(session=session)
            es_uow = AsyncESUnitOfWork(client=client)
            async with sql_uow, es_uow:
                # Postgres refuses a write from this transaction, so read-only is
                # enforced rather than left to the services this assembles.
                await session.execute(text("SET TRANSACTION READ ONLY"))
                deduplication_service = DeduplicationService(
                    ReferenceAntiCorruptionService(
                        sign_url=self._blob_repository.get_signed_url
                    ),
                    sql_uow,
                    es_uow,
                )
                assessment_service = DeduplicationAssessmentService(
                    candidate_selector=deduplication_service.get_deduplication_candidates,
                    reference_reader=sql_uow.references,
                    pair_scorer=self._pair_scorer,
                )
                return await assessment_service.evaluate_supplied(
                    incoming,
                    selection_input,
                    retrieval_policy=retrieval_policy,
                    k=k,
                )


def resolve_pair_scorer(factory_path: str) -> PairScorer:
    """
    Build the scorer named as ``module:factory``.

    :param factory_path: Import path of a zero-argument scorer factory.
    :type factory_path: str
    :return: The constructed pair scorer.
    :rtype: PairScorer
    :raises RuntimeError: If the path does not separate a module from a factory.
    """
    module_path, separator, factory_name = factory_path.rpartition(":")
    if not separator or not module_path or not factory_name:
        # Without the separator the remainder imports as nonsense rather than
        # reporting the argument that was wrong.
        msg = f"Pair scorer {factory_path!r} must be given as 'module:factory'."
        raise RuntimeError(msg)

    factory = getattr(importlib.import_module(module_path), factory_name)
    return factory()


async def current_index_version() -> str:
    """
    Read the index the alias resolves to now.

    Stamped from the cluster rather than asserted, so the manifest names the index
    the run actually searched.

    :return: The physical reference index name.
    :rtype: str
    :raises RuntimeError: If the alias resolves to no index.
    """
    async with es_manager.client() as client:
        es_uow = AsyncESUnitOfWork(client=client)
        async with es_uow:
            index_version = await es_uow.references.get_current_index_name()
    if index_version is None:
        msg = "The reference index alias resolves to no index, so nothing to stamp."
        raise RuntimeError(msg)
    return index_version


async def run_evaluation(args: argparse.Namespace) -> EvaluationRunArtifacts:
    """Assess every record of the input blob and write the run's bundle."""
    # Minted here rather than accepted from the operator: the runner restarts at
    # line one, so reusing an id overwrites a finished bundle instead of resuming.
    run_id = uuid7()
    pair_scorer = resolve_pair_scorer(args.pair_scorer)
    blob_repository = BlobRepository()

    try:
        # Inside the cleanup scope, so a failure part-way through initialisation
        # still releases whatever was opened before it.
        logger.info("Connecting to %s infrastructure", settings.env.value)
        db_manager.init(settings.db_config, APPLICATION_NAME)
        await es_manager.init(settings.es_config)

        configuration = EvaluationRunConfiguration(
            dataset_version=args.dataset_version,
            environment=settings.env.value,
            corpus_observed_at=args.corpus_observed_at,
            elasticsearch_index_version=await current_index_version(),
            code_commit=args.code_commit,
            retrieval_policy=args.retrieval_policy,
            k=args.k,
            deduper=pair_scorer.metadata,
        )
        logger.info(
            "Starting evaluation run %s over %s",
            run_id,
            args.input,
            run_configuration=configuration.model_dump(mode="json"),
        )
        runner = DeduplicationEvaluationRunner(
            assessor=EvaluationAssessor(
                blob_repository=blob_repository, pair_scorer=pair_scorer
            )
        )
        artifacts = await runner.run(
            run_id=run_id,
            input_file=BlobStorageFile.from_uri(args.input),
            blob_repository=blob_repository,
            configuration=configuration,
            max_input_bytes=settings.evaluation_input_max_byte_size,
        )
    finally:
        logger.info("Releasing infrastructure clients")
        await db_manager.close()
        await es_manager.close()
        await close_blob_clients()

    logger.info(
        "Evaluation run %s complete: %s",
        artifacts.run_id,
        artifacts.manifest_file.to_uri(),
    )
    return artifacts


def aware_datetime(value: str) -> datetime.datetime:
    """
    Parse an ISO-8601 timestamp, rejecting one with no offset.

    A naive corpus observation cannot be compared across the runs and environments
    the manifest exists to compare.
    """
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = f"Timestamp {value!r} needs a UTC offset."
        raise argparse.ArgumentTypeError(msg)
    return parsed


def argument_parser() -> argparse.ArgumentParser:
    """Create the argument parser for an evaluation run."""
    parser = argparse.ArgumentParser(
        description="Run a read-only deduplication evaluation over a JSONL blob."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        required=True,
        help="Blob URI of the input JSONL, e.g. minio://operations/set/queries.jsonl.",
    )
    parser.add_argument(
        "-d",
        "--dataset-version",
        type=str,
        required=True,
        help="Dataset version every input record must declare.",
    )
    parser.add_argument(
        "-c",
        "--corpus-observed-at",
        type=aware_datetime,
        required=True,
        help="ISO-8601 timestamp, with offset, of the corpus state being measured.",
    )
    parser.add_argument(
        "--code-commit",
        type=str,
        required=True,
        help='Commit the run executed, e.g. "$(git rev-parse HEAD)".',
    )
    parser.add_argument(
        "--pair-scorer",
        type=str,
        required=True,
        help="Import path of a zero-argument scorer factory, as 'module:factory'.",
    )
    parser.add_argument(
        "-p",
        "--retrieval-policy",
        type=RetrievalPolicyName,
        choices=list(RetrievalPolicyName),
        default=settings.dedup_scoring.default_retrieval_policy,
        help="Retrieval policy to evaluate. Defaults to the environment's policy.",
    )
    parser.add_argument(
        "-k",
        type=int,
        default=settings.dedup_scoring.candidate_k,
        help="Candidates to retrieve per record. Defaults to the environment's k.",
    )
    return parser


if __name__ == "__main__":
    asyncio.run(run_evaluation(argument_parser().parse_args()))
