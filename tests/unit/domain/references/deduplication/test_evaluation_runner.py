"""Tests for the deduplication evaluation runner."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest

from app.core.exceptions import DeduplicationError
from app.domain.references.models.models import (
    Candidate,
    CandidateElasticsearchRoute,
    CandidateSelectionDiagnostics,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    DeduplicationPairResult,
    ExternalIdentifierType,
    InputSearchability,
    RetrievalPolicyName,
    ScoredDeduplicationCandidate,
)
from app.domain.references.services.deduplication_evaluation_runner import (
    DeduplicationEvaluationRunner,
    EvaluationRunConfiguration,
)
from app.persistence.blob.models import BlobStorageFile, BlobStorageLocation
from app.persistence.blob.repository import BlobRepository


def _configuration(
    policy: RetrievalPolicyName = RetrievalPolicyName.CANDIDATE_SELECTION_V1,
) -> EvaluationRunConfiguration:
    return EvaluationRunConfiguration(
        dataset_version="retrieval-query-set/v1",
        environment="test",
        corpus_observed_at=datetime(2026, 8, 10, 3, 30, tzinfo=UTC),
        elasticsearch_index_version="reference_v3",
        code_commit="test-commit",
        retrieval_policy=policy,
        k=10,
        deduper=DeduperMetadata(
            package_version="fake-1",
            configuration_hash="fake-config",
            threshold=0.85,
        ),
    )


def _line(
    query_id: str,
    *,
    year: int | None = 2024,
    route_applicability: list[str] | None = None,
    input_identifiers: list[str] | None = None,
    excluded_reference_ids: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "query_id": query_id,
            "input_reference": {
                "title": f"Study {query_id}",
                "authors": ["First Author", "Middle Author", "Last Author"],
                "year": year,
            },
            "input_identifiers": input_identifiers or ["open_alex:W1"],
            "route_applicability": route_applicability or ["fuzzy"],
            "excluded_reference_ids": excluded_reference_ids or [],
            "dataset_version": "retrieval-query-set/v1",
        }
    )


def _assessment(incoming_id, *, with_pairs: bool = False):
    candidates = []
    scored_candidates = []
    if with_pairs:
        for rank, probability, clears_threshold in (
            (1, 0.91, True),
            (2, 0.51, False),
            (3, None, None),
        ):
            candidate = Candidate(
                reference_id=uuid7(),
                rank=rank,
                routes=[
                    CandidateElasticsearchRoute(
                        policy="candidate_selection_v1",
                        rank=rank,
                        score=float(10 - rank),
                    )
                ],
            )
            candidates.append(candidate)
            scored_candidates.append(
                ScoredDeduplicationCandidate(
                    candidate=candidate,
                    pair_result=(
                        DeduplicationPairResult(probability=probability)
                        if probability is not None
                        else DeduplicationPairResult(unscorable_reason="missing title")
                    ),
                    clears_threshold=clears_threshold,
                )
            )
    return DeduplicationAssessment(
        incoming_reference_id=incoming_id,
        candidate_selection=CandidateSelectionResult(
            retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
            index_version="reference_v3",
            k_requested=10,
            input_searchability=InputSearchability(
                searchable=True,
                reason="The input has a title and authors.",
            ),
            candidates=candidates,
            diagnostics=CandidateSelectionDiagnostics(),
        ),
        deduper=DeduperMetadata(
            package_version="fake-1",
            configuration_hash="fake-config",
            threshold=0.85,
        ),
        scored_candidates=scored_candidates,
        outcome=(
            DeduplicationAssessmentOutcome.NO_PROPOSAL
            if with_pairs
            else DeduplicationAssessmentOutcome.PROPOSE_CANONICAL
        ),
    )


def _blob_repository(source: bytes) -> tuple[BlobRepository, dict[str, bytes]]:
    async def chunks():
        midpoint = len(source) // 2
        for chunk in (source[:midpoint], source[midpoint:]):
            yield chunk

    uploaded: dict[str, bytes] = {}

    async def upload(content, path, filename, **_kwargs):
        assert isinstance(content, BytesIO)
        uploaded[filename] = content.getvalue()
        return BlobStorageFile(
            location=BlobStorageLocation.MINIO,
            container="test",
            path=path,
            filename=filename,
        )

    repository = MagicMock(spec=BlobRepository)
    repository.stream_chunks_from_blob_storage.return_value = chunks()
    repository.upload_file_to_blob_storage = AsyncMock(side_effect=upload)
    return repository, uploaded


@pytest.mark.asyncio
async def test_run_writes_complete_reviewable_bundle():
    """The public run contract preserves input identity and writes manifest last."""
    run_id = uuid7()
    input_file = BlobStorageFile.from_uri(
        "azure://dedup-evals/datasets/retrieval-query-set/v1/records.jsonl"
    )
    source = (_line("assessed") + "\nnot json\n").encode()
    repository, uploaded = _blob_repository(source)
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, *_args, **_kwargs: (
        _assessment(incoming.id, with_pairs=True)
    )

    artifacts = await DeduplicationEvaluationRunner(assessor=assessor).run(
        run_id=run_id,
        input_file=input_file,
        blob_repository=repository,
        configuration=_configuration(),
    )

    expected_path = f"deduplication_evaluation/{run_id}"
    upload = cast(AsyncMock, repository.upload_file_to_blob_storage)
    assert [call.kwargs["filename"] for call in upload.await_args_list] == [
        "record-results.jsonl",
        "pair-results.jsonl",
        "summary.md",
        "manifest.json",
    ]
    assert {
        file.filename: file.path
        for file in (
            artifacts.record_results_file,
            artifacts.pair_results_file,
            artifacts.summary_file,
            artifacts.manifest_file,
        )
    } == {filename: expected_path for filename in uploaded}
    assert artifacts.input_file == input_file
    assert artifacts.input_byte_size == len(source)
    assert artifacts.input_sha256 == hashlib.sha256(source).hexdigest()

    records = [json.loads(row) for row in uploaded["record-results.jsonl"].splitlines()]
    pairs = [json.loads(row) for row in uploaded["pair-results.jsonl"].splitlines()]
    assert [
        (row["query_id"], row["line_number"], row["status"]) for row in records
    ] == [
        ("assessed", 1, "assessed"),
        (None, 2, "input_invalid"),
    ]
    assert records[1]["error"]["code"] == "invalid_json"
    assert [row["clears_threshold"] for row in pairs] == [True, False, None]
    assert all(row["query_id"] == "assessed" for row in pairs)
    assert pairs[0]["retrieval_routes"][0]["policy"] == "candidate_selection_v1"
    assert pairs[0]["pair_result"]["probability"] == 0.91

    summary = uploaded["summary.md"].decode()
    for expected in (
        "Assessed records: 1",
        "Invalid input records: 1",
        "Evaluation-failed records: 0",
        "- `no_proposal`: 1",
        "- Clears threshold: 1",
        "- Below threshold: 1",
        "- Unscorable: 1",
    ):
        assert expected in summary

    manifest = json.loads(uploaded["manifest.json"])
    assert manifest["input"] == {
        "uri": input_file.to_uri(),
        "dataset_version": "retrieval-query-set/v1",
        "byte_size": len(source),
        "sha256": hashlib.sha256(source).hexdigest(),
    }
    assert manifest["configuration"] == _configuration().model_dump(mode="json")
    assert manifest["counts"] == {
        "record_statuses": {
            "assessed": 1,
            "input_invalid": 1,
            "evaluation_failed": 0,
        },
        "pair_rows": 3,
    }
    for filename, schema in (
        ("record-results.jsonl", "evaluation-record-result/v1"),
        ("pair-results.jsonl", "evaluation-pair-result/v1"),
        ("summary.md", "deduplication-evaluation-summary/v1"),
    ):
        assert manifest["artifacts"][filename] == {
            "uri": f"minio://test/{expected_path}/{filename}",
            "schema_version": schema,
            "byte_size": len(uploaded[filename]),
            "sha256": hashlib.sha256(uploaded[filename]).hexdigest(),
        }


@pytest.mark.asyncio
async def test_run_builds_yearless_and_fuzzy_only_assessment_inputs():
    """Frozen inputs preserve scoring data while controlling retrieval routes."""
    held_reference_id = uuid7()
    source = (
        _line(
            "yearless",
            year=None,
            route_applicability=["identifier", "fuzzy"],
            excluded_reference_ids=[str(held_reference_id)],
        )
        + "\n"
        + _line("fuzzy-only")
    ).encode()
    repository, _uploaded = _blob_repository(source)
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, *_args, **_kwargs: (
        _assessment(incoming.id)
    )
    policy = RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1

    await DeduplicationEvaluationRunner(assessor=assessor).run(
        run_id=uuid7(),
        input_file=BlobStorageFile.from_uri("azure://dedup-evals/input.jsonl"),
        blob_repository=repository,
        configuration=_configuration(policy),
    )

    first_incoming, first_selection = assessor.evaluate_supplied.await_args_list[0].args
    second_incoming, second_selection = assessor.evaluate_supplied.await_args_list[
        1
    ].args
    bibliography = first_incoming.enhancements[0].content
    assert first_incoming.id.version == 7
    assert first_incoming.identifiers[0].identifier == "W1"
    assert bibliography.publication_year is None
    assert [
        (author.display_name, author.position) for author in bibliography.authorship
    ] == [
        ("First Author", "first"),
        ("Middle Author", "middle"),
        ("Last Author", "last"),
    ]
    assert first_selection.excluded_reference_id == held_reference_id
    assert (
        first_selection.identifiers[0].identifier_type
        is ExternalIdentifierType.OPEN_ALEX
    )
    assert second_incoming.identifiers[0].identifier == "W1"
    assert second_selection.identifiers == []
    assert all(
        call.kwargs == {"retrieval_policy": policy, "k": 10}
        for call in assessor.evaluate_supplied.await_args_list
    )


@pytest.mark.asyncio
async def test_run_records_expected_failures_and_continues():
    """Every non-blank line gets an envelope and expected failures stay local."""
    exclusions = [str(uuid7()), str(uuid7())]
    source = "\n".join(
        [
            _line("first"),
            "   ",
            '{"query_id": "broken"',
            "[]",
            _line("too-many", excluded_reference_ids=exclusions),
            _line("bad-id", input_identifiers=["unknown:value"]),
            _line("assessment-failed"),
            _line("last"),
        ]
    ).encode()
    repository, uploaded = _blob_repository(source)
    call_count = 0

    async def assess(incoming, *_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            message = "candidate hydration failed"
            raise DeduplicationError(message)
        return _assessment(incoming.id)

    assessor = AsyncMock(side_effect=assess)
    assessor.evaluate_supplied = AsyncMock(side_effect=assess)

    await DeduplicationEvaluationRunner(assessor=assessor).run(
        run_id=uuid7(),
        input_file=BlobStorageFile.from_uri("azure://dedup-evals/input.jsonl"),
        blob_repository=repository,
        configuration=_configuration(),
    )

    records = [json.loads(row) for row in uploaded["record-results.jsonl"].splitlines()]
    assert [row["line_number"] for row in records] == [1, 3, 4, 5, 6, 7, 8]
    assert [row["status"] for row in records] == [
        "assessed",
        "input_invalid",
        "input_invalid",
        "input_invalid",
        "input_invalid",
        "evaluation_failed",
        "assessed",
    ]
    assert [row["error"]["code"] for row in records[1:6]] == [
        "invalid_json",
        "invalid_record",
        "invalid_record",
        "invalid_record",
        "evaluation_failed",
    ]
    assert records[5]["query_id"] == "assessment-failed"
    assert "candidate hydration failed" in records[5]["error"]["message"]
    assert assessor.evaluate_supplied.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ValueError("unexpected scorer defect"), id="unexpected"),
        pytest.param(asyncio.CancelledError(), id="cancelled"),
    ],
)
async def test_run_propagates_non_record_failures(error):
    """Programming errors and cancellation abort the run."""
    repository, uploaded = _blob_repository(_line("failed").encode())
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = error

    with pytest.raises(type(error)):
        await DeduplicationEvaluationRunner(assessor=assessor).run(
            run_id=uuid7(),
            input_file=BlobStorageFile.from_uri("azure://dedup-evals/input.jsonl"),
            blob_repository=repository,
            configuration=_configuration(),
        )

    assert uploaded == {}
