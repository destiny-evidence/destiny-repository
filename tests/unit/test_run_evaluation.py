import argparse
import contextlib
import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid7

import pytest

from app import run_evaluation
from app.domain.references.models.models import (
    CandidateSelectionInput,
    DeduperMetadata,
    RetrievalPolicyName,
)
from app.persistence.blob.repository import BlobRepository
from app.run_evaluation import (
    EvaluationAssessor,
    aware_datetime,
    current_index_version,
    resolve_pair_scorer,
)
from tests.factories import ReferenceFactory

NAMED_SCORER = object()
STAMPED_METADATA = DeduperMetadata(
    package_version="1.2.3", configuration_hash="cfg-hash", threshold=0.8
)
STAMPED_INDEX = "reference-000042"
_REQUIRED_ARGUMENTS = [
    "--input",
    "minio://operations/set/queries.jsonl",
    "--dataset-version",
    "retrieval-query-set/v1",
    "--corpus-observed-at",
    "2026-08-17T00:00:00+00:00",
    "--code-commit",
    "abc123",
    "--pair-scorer",
    "module:factory",
]


def build_named_scorer():
    """Factory the scorer-resolution test names by import path."""
    return NAMED_SCORER


def build_stamped_scorer():
    """Factory the run tests name, carrying identifiable scorer metadata."""
    scorer = MagicMock()
    scorer.metadata = STAMPED_METADATA
    return scorer


class _RecordingSession:
    """Stand-in session keeping the statements the assessor issued."""

    def __init__(self):
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))

    async def close(self):
        pass

    async def rollback(self):
        pass


@contextlib.asynccontextmanager
async def _yielding(value):
    yield value


def _selection_input():
    return CandidateSelectionInput(title="A title", authors=["Ann Author"])


def _assessor_under_test(monkeypatch, session_source, assessment=None):
    """Wire an assessor whose only real collaborator is the session it opens."""
    monkeypatch.setattr(run_evaluation.db_manager, "session", session_source)
    monkeypatch.setattr(
        run_evaluation.es_manager, "client", lambda: _yielding(MagicMock())
    )
    service = MagicMock()
    service.evaluate_supplied = AsyncMock(return_value=assessment or MagicMock())
    monkeypatch.setattr(
        run_evaluation,
        "DeduplicationAssessmentService",
        MagicMock(return_value=service),
    )
    return EvaluationAssessor(
        blob_repository=MagicMock(spec=BlobRepository),
        pair_scorer=MagicMock(),
    )


def test_aware_datetime_rejects_a_naive_timestamp():
    """A corpus observation with no offset cannot be compared across runs."""
    with pytest.raises(argparse.ArgumentTypeError, match="needs a UTC offset"):
        aware_datetime("2026-08-17T00:00:00")


def test_aware_datetime_keeps_the_supplied_offset():
    """The offset is preserved rather than normalised, so the manifest is literal."""
    parsed = aware_datetime("2026-08-17T10:30:00+10:00")

    assert parsed.utcoffset().total_seconds() == 10 * 60 * 60


@pytest.mark.parametrize(
    "factory_path",
    ["module.without.a.factory", ":factory", "module:", ""],
)
def test_resolve_pair_scorer_rejects_a_path_missing_either_half(factory_path):
    """Without both halves the remainder imports as nonsense, not as an error."""
    with pytest.raises(RuntimeError, match="must be given as 'module:factory'"):
        resolve_pair_scorer(factory_path)


def test_resolve_pair_scorer_builds_the_named_factory():
    """The scorer comes from the path given, so no stand-in is chosen for it."""
    assert resolve_pair_scorer(f"{__name__}:build_named_scorer") is NAMED_SCORER


@pytest.mark.asyncio
async def test_current_index_version_refuses_an_absent_alias(monkeypatch):
    """Without an index version the manifest cannot say what the run searched."""
    es_uow = MagicMock()
    es_uow.references.get_current_index_name = AsyncMock(return_value=None)
    monkeypatch.setattr(
        run_evaluation, "AsyncESUnitOfWork", MagicMock(return_value=es_uow)
    )
    monkeypatch.setattr(
        run_evaluation.es_manager, "client", lambda: _yielding(MagicMock())
    )

    with pytest.raises(RuntimeError, match="resolves to no index"):
        await current_index_version()


@pytest.mark.asyncio
async def test_assessor_makes_the_transaction_read_only_before_assessing(monkeypatch):
    """The run cannot mutate the corpus it measures."""
    session = _RecordingSession()
    statements_when_assessed: list[str] = []
    assessment = MagicMock()
    assessor = _assessor_under_test(
        monkeypatch, lambda: _yielding(session), assessment=assessment
    )

    def record_statements_seen(*_args, **_kwargs):
        statements_when_assessed.extend(session.statements)
        return assessment

    service = run_evaluation.DeduplicationAssessmentService.return_value
    service.evaluate_supplied.side_effect = record_statements_seen

    result = await assessor.evaluate_supplied(
        ReferenceFactory.build(), _selection_input()
    )

    assert statements_when_assessed == ["SET TRANSACTION READ ONLY"]
    assert result is assessment


@pytest.mark.asyncio
async def test_assessor_holds_no_session_between_records(monkeypatch):
    """A run of up to an hour must not pin one snapshot open for its duration."""
    sessions: list[_RecordingSession] = []

    def new_session():
        sessions.append(_RecordingSession())
        return _yielding(sessions[-1])

    assessor = _assessor_under_test(monkeypatch, new_session)

    for _ in range(2):
        await assessor.evaluate_supplied(ReferenceFactory.build(), _selection_input())

    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_assessor_passes_the_run_configuration_through(monkeypatch):
    """A per-record override must reach the assessment, or the manifest lies."""
    assessor = _assessor_under_test(monkeypatch, lambda: _yielding(_RecordingSession()))
    policy = run_evaluation.RetrievalPolicyName.CURRENT_FUZZY_V1

    await assessor.evaluate_supplied(
        ReferenceFactory.build(),
        _selection_input(),
        retrieval_policy=policy,
        k=25,
    )

    service = run_evaluation.DeduplicationAssessmentService.return_value
    assert service.evaluate_supplied.await_args.kwargs == {
        "retrieval_policy": policy,
        "k": 25,
    }


def test_argument_parser_defaults_no_provenance_field():
    """A bundle whose provenance is partly defaulted cannot be compared to another."""
    parser = run_evaluation.argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--input", "minio://operations/set/queries.jsonl"])


def test_argument_parser_takes_the_retrieval_defaults_from_settings():
    """An unstated policy is the one production runs, not a per-script choice."""
    args = run_evaluation.argument_parser().parse_args(_REQUIRED_ARGUMENTS)

    scoring = run_evaluation.settings.dedup_scoring
    assert args.retrieval_policy == scoring.default_retrieval_policy
    assert args.k == scoring.candidate_k


def _run_arguments(**overrides):
    """Build the parsed arguments of a run, without going through the parser."""
    return argparse.Namespace(
        **{
            "input": "minio://operations/set/queries.jsonl",
            "dataset_version": "retrieval-query-set/v1",
            "corpus_observed_at": datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
            "code_commit": "abc123",
            "pair_scorer": f"{__name__}:build_stamped_scorer",
            "retrieval_policy": RetrievalPolicyName.CURRENT_FUZZY_V1,
            "k": 7,
            "run_id": None,
            **overrides,
        }
    )


def _stub_infrastructure(monkeypatch):
    """
    Replace every client the run opens, recording the order they are released.

    :return: The release log and the stubbed runner the driver will drive.
    """
    released: list[str] = []
    monkeypatch.setattr(run_evaluation, "BlobRepository", MagicMock())
    monkeypatch.setattr(run_evaluation.db_manager, "init", MagicMock())
    monkeypatch.setattr(
        run_evaluation.db_manager,
        "close",
        AsyncMock(side_effect=lambda: released.append("db")),
    )
    monkeypatch.setattr(run_evaluation.es_manager, "init", AsyncMock())
    monkeypatch.setattr(
        run_evaluation.es_manager,
        "close",
        AsyncMock(side_effect=lambda: released.append("es")),
    )
    monkeypatch.setattr(
        run_evaluation,
        "close_blob_clients",
        AsyncMock(side_effect=lambda: released.append("blob")),
    )
    monkeypatch.setattr(
        run_evaluation, "current_index_version", AsyncMock(return_value=STAMPED_INDEX)
    )
    monkeypatch.setattr(run_evaluation, "DeduplicationEvaluationRunner", MagicMock())
    runner = run_evaluation.DeduplicationEvaluationRunner.return_value
    # An AsyncMock's own return value is another AsyncMock, whose artifact fields
    # would then be coroutines the driver logs instead of the bundle's URIs.
    runner.run = AsyncMock(return_value=MagicMock())
    return released, runner


@pytest.mark.asyncio
async def test_run_evaluation_releases_its_clients_when_the_run_fails(monkeypatch):
    """A failed run must not leave the environment's pooled clients open."""
    released, runner = _stub_infrastructure(monkeypatch)
    runner.run.side_effect = RuntimeError("assessment exploded")

    with pytest.raises(RuntimeError, match="assessment exploded"):
        await run_evaluation.run_evaluation(_run_arguments())

    assert released == ["db", "es", "blob"]


@pytest.mark.asyncio
async def test_run_evaluation_stamps_a_run_id_when_none_is_supplied(monkeypatch):
    """The bundle is written under the run id, so a run cannot proceed without one."""
    _released, runner = _stub_infrastructure(monkeypatch)

    await run_evaluation.run_evaluation(_run_arguments(run_id=None))

    assert isinstance(runner.run.await_args.kwargs["run_id"], UUID)


@pytest.mark.asyncio
async def test_run_evaluation_releases_the_database_when_search_will_not_start(
    monkeypatch,
):
    """Initialisation is partial when it fails, and the earlier client still leaks."""
    released, _runner = _stub_infrastructure(monkeypatch)
    monkeypatch.setattr(
        run_evaluation.es_manager,
        "init",
        AsyncMock(side_effect=ConnectionError("no cluster")),
    )

    with pytest.raises(ConnectionError, match="no cluster"):
        await run_evaluation.run_evaluation(_run_arguments())

    assert released == ["db", "es", "blob"]


@pytest.mark.asyncio
async def test_run_evaluation_caps_the_input_it_will_read(monkeypatch):
    """An unbounded input would be digested and buffered before anything checks it."""
    _released, runner = _stub_infrastructure(monkeypatch)

    await run_evaluation.run_evaluation(_run_arguments())

    assert (
        runner.run.await_args.kwargs["max_input_bytes"]
        == run_evaluation.settings.evaluation_input_max_byte_size
    )


@pytest.mark.asyncio
async def test_run_evaluation_mints_a_distinct_run_id_each_time(monkeypatch):
    """The runner restarts at line one, so a reused id would overwrite a bundle."""
    _released, runner = _stub_infrastructure(monkeypatch)

    await run_evaluation.run_evaluation(_run_arguments())
    await run_evaluation.run_evaluation(_run_arguments())

    first, second = (call.kwargs["run_id"] for call in runner.run.await_args_list)
    assert first != second


def test_argument_parser_refuses_a_caller_supplied_run_id():
    """An operator cannot name a path that already holds a finished bundle."""
    parser = run_evaluation.argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([*_REQUIRED_ARGUMENTS, "--run-id", str(uuid7())])


@pytest.mark.asyncio
async def test_run_evaluation_stamps_the_observed_provenance(monkeypatch):
    """The manifest has to name what ran, not what the operator hoped would run."""
    _released, runner = _stub_infrastructure(monkeypatch)

    await run_evaluation.run_evaluation(_run_arguments())

    configuration = runner.run.await_args.kwargs["configuration"]
    assert configuration.elasticsearch_index_version == STAMPED_INDEX
    assert configuration.deduper == STAMPED_METADATA
    assert configuration.environment == run_evaluation.settings.env.value
    assert configuration.retrieval_policy == RetrievalPolicyName.CURRENT_FUZZY_V1
    assert configuration.k == 7
