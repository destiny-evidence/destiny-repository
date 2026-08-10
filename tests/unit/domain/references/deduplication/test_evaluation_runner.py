"""Tests for the deduplication evaluation runner."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid7

import pytest

from app.core.exceptions import BlobStorageError, DeduplicationError
from app.domain.references.models.models import (
    Candidate,
    CandidateElasticsearchRoute,
    CandidateIdentifier,
    CandidateIdentifierRoute,
    CandidateSelectionDiagnostics,
    CandidateSelectionInput,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    DeduplicationFieldComparison,
    DeduplicationFieldStatus,
    DeduplicationPairResult,
    ExternalIdentifierType,
    InputSearchability,
    RetrievalPolicyName,
    ScoredDeduplicationCandidate,
)
from app.domain.references.services.deduplication_evaluation_runner import (
    DeduplicationEvaluationRunner,
    EvaluationPairResult,
    EvaluationRecordResult,
    EvaluationRecordStatus,
    EvaluationRunConfiguration,
)
from app.persistence.blob.models import BlobStorageFile, BlobStorageLocation
from app.persistence.blob.repository import BlobRepository


def _assessment(
    incoming_reference_id,
    retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
):
    return DeduplicationAssessment(
        incoming_reference_id=incoming_reference_id,
        candidate_selection=CandidateSelectionResult(
            retrieval_policy=retrieval_policy,
            index_version="reference_v3",
            k_requested=10,
            input_searchability=InputSearchability(
                searchable=True,
                reason="The input has a title and authors.",
            ),
            diagnostics=CandidateSelectionDiagnostics(),
        ),
        deduper=DeduperMetadata(
            package_version="fake-1",
            configuration_hash="fake-config",
            threshold=0.85,
        ),
        outcome=DeduplicationAssessmentOutcome.PROPOSE_CANONICAL,
    )


def _assessment_with_pair_evidence(
    incoming_reference_id,
    retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
):
    assessment = _assessment(incoming_reference_id, retrieval_policy)
    candidates = [
        ScoredDeduplicationCandidate(
            candidate=Candidate(
                reference_id=uuid7(),
                rank=rank,
                routes=[
                    CandidateElasticsearchRoute(
                        policy=retrieval_policy.value,
                        rank=rank,
                        score=score,
                    )
                ],
            ),
            pair_result=(
                DeduplicationPairResult(probability=probability)
                if probability is not None
                else DeduplicationPairResult(unscorable_reason="missing title")
            ),
            clears_threshold=clears_threshold,
        )
        for rank, score, probability, clears_threshold in (
            (1, 9.1, 0.91, True),
            (2, 5.1, 0.51, False),
            (3, 2.1, None, None),
        )
    ]
    return assessment.model_copy(
        update={
            "candidate_selection": assessment.candidate_selection.model_copy(
                update={"candidates": [item.candidate for item in candidates]}
            ),
            "scored_candidates": candidates,
            "outcome": DeduplicationAssessmentOutcome.NO_PROPOSAL,
            "threshold_clearing_candidate_ids": [candidates[0].candidate.reference_id],
            "unscorable_candidate_ids": [candidates[2].candidate.reference_id],
        }
    )


def _run_configuration() -> EvaluationRunConfiguration:
    return EvaluationRunConfiguration(
        dataset_version="retrieval-query-set/v1",
        environment="test",
        corpus_observed_at=datetime(2026, 8, 10, 3, 30, tzinfo=UTC),
        elasticsearch_index_version="reference_v3",
        code_commit="test-commit",
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
        deduper=DeduperMetadata(
            package_version="fake-1",
            configuration_hash="fake-config",
            threshold=0.85,
        ),
    )


def _expected_artifact(
    file: BlobStorageFile, content: bytes, schema_version: str
) -> dict[str, object]:
    return {
        "uri": file.to_uri(),
        "schema_version": schema_version,
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _valid_line(query_id: str, **updates: object) -> str:
    record: dict[str, object] = {
        "query_id": query_id,
        "input_reference": {
            "title": "A study",
            "authors": ["First Author"],
            "year": 2024,
        },
        "input_identifiers": ["open_alex:W1"],
        "route_applicability": ["fuzzy"],
        "excluded_reference_ids": [],
        "dataset_version": "retrieval-query-set/v1",
    }
    record.update(updates)
    return json.dumps(record)


@pytest.mark.asyncio
async def test_evaluate_line_assesses_yearless_supplied_record_with_correlation():
    """A frozen row is assessed without first resolving it to a held record."""
    run_id = uuid7()
    held_reference_id = uuid7()
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, _selection, **_kwargs: (
        _assessment(
            incoming.id,
            RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
        )
    )
    runner = DeduplicationEvaluationRunner(assessor=assessor)
    line = f"""{{
        "query_id": "oa-km:W1:W2",
        "input_reference": {{
            "title": "A yearless study",
            "authors": ["First Author", "Middle Author", "Last Author"],
            "year": null
        }},
        "input_identifiers": ["open_alex:W1"],
        "route_applicability": ["identifier", "fuzzy"],
        "excluded_reference_ids": ["{held_reference_id}"],
        "dataset_version": "retrieval-query-set/v1",
        "source_group": "openalex"
    }}"""

    result = await runner.evaluate_line(
        run_id=run_id,
        line=line,
        line_number=42,
        retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
        k=10,
    )

    assert result.incoming_reference_id is not None
    assert result == EvaluationRecordResult(
        run_id=run_id,
        query_id="oa-km:W1:W2",
        line_number=42,
        status=EvaluationRecordStatus.ASSESSED,
        incoming_reference_id=result.incoming_reference_id,
        assessment=_assessment(
            result.incoming_reference_id,
            RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
        ),
    )
    incoming, selection = assessor.evaluate_supplied.await_args.args
    biblio = incoming.enhancements[0].content
    assert {
        "id": incoming.id,
        "id_version": incoming.id.version,
        "visibility": incoming.visibility,
        "identifier": (
            incoming.identifiers[0].identifier_type,
            incoming.identifiers[0].identifier,
        ),
        "enhancement_source": incoming.enhancements[0].source,
        "title": biblio.title,
        "publication_year": biblio.publication_year,
        "authors": [
            (author.display_name, author.position) for author in biblio.authorship
        ],
    } == {
        "id": result.incoming_reference_id,
        "id_version": 7,
        "visibility": "public",
        "identifier": (ExternalIdentifierType.OPEN_ALEX, "W1"),
        "enhancement_source": "retrieval-query-set/v1",
        "title": "A yearless study",
        "publication_year": None,
        "authors": [
            ("First Author", "first"),
            ("Middle Author", "middle"),
            ("Last Author", "last"),
        ],
    }
    assert selection == CandidateSelectionInput(
        title="A yearless study",
        authors=["First Author", "Middle Author", "Last Author"],
        publication_year=None,
        identifiers=[
            CandidateIdentifier(
                identifier="W1",
                identifier_type=ExternalIdentifierType.OPEN_ALEX,
            )
        ],
        excluded_reference_id=held_reference_id,
    )
    assert assessor.evaluate_supplied.await_args.kwargs == {
        "retrieval_policy": RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
        "k": 10,
    }


@pytest.mark.asyncio
async def test_evaluate_line_withholds_identifiers_from_fuzzy_only_query():
    """Dataset identifiers remain scorer input without leaking into retrieval."""
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, _selection, **_kwargs: (
        _assessment(incoming.id)
    )
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    await runner.evaluate_line(
        run_id=uuid7(),
        line="""{
            "query_id": "oa-km:W3:W4",
            "input_reference": {
                "title": "A fuzzy-only study",
                "authors": ["First Author"],
                "year": 2024
            },
            "input_identifiers": ["open_alex:W3"],
            "route_applicability": ["fuzzy"],
            "excluded_reference_ids": [],
            "dataset_version": "retrieval-query-set/v1"
        }""",
        line_number=1,
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
    )

    incoming, selection = assessor.evaluate_supplied.await_args.args
    assert incoming.identifiers[0].identifier == "W3"
    assert selection.identifiers == []


@pytest.mark.asyncio
async def test_evaluate_lines_records_invalid_json_and_continues():
    """Every non-blank physical line gets an envelope without aborting later rows."""
    run_id = uuid7()
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, _selection, **_kwargs: (
        _assessment(incoming.id)
    )
    runner = DeduplicationEvaluationRunner(assessor=assessor)
    lines = AsyncMock()
    lines.__aiter__.return_value = [
        _valid_line("first"),
        "   ",
        '{"query_id": "broken"',
        _valid_line("last"),
    ]

    results = [
        result
        async for result in runner.evaluate_lines(
            run_id=run_id,
            lines=lines,
            retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
            k=10,
        )
    ]

    assert [result.line_number for result in results] == [1, 3, 4]
    assert [result.status for result in results] == [
        "assessed",
        "input_invalid",
        "assessed",
    ]
    invalid = results[1]
    assert invalid.run_id == run_id
    assert invalid.query_id is None
    assert invalid.incoming_reference_id is None
    assert invalid.assessment is None
    assert invalid.error is not None
    assert invalid.error.code == "invalid_json"
    assert "Invalid JSON" in invalid.error.message
    assert assessor.evaluate_supplied.await_count == 2


@pytest.mark.asyncio
async def test_evaluate_line_rejects_multiple_self_exclusions():
    """The singular assessment query must not silently choose one exclusion."""
    assessor = AsyncMock()
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    result = await runner.evaluate_line(
        run_id=uuid7(),
        line=_valid_line(
            "too-many-exclusions",
            excluded_reference_ids=[str(uuid7()), str(uuid7())],
        ),
        line_number=7,
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
    )

    assert result.query_id == "too-many-exclusions"
    assert result.status == "input_invalid"
    assert result.error is not None
    assert result.error.code == "invalid_record"
    assert "excluded_reference_ids" in result.error.message
    assessor.evaluate_supplied.assert_not_awaited()


@pytest.mark.asyncio
async def test_evaluate_line_records_identifier_conversion_failure():
    """An invalid SDK identifier is a record error, not a run failure."""
    assessor = AsyncMock()
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    result = await runner.evaluate_line(
        run_id=uuid7(),
        line=_valid_line("bad-identifier", input_identifiers=["unknown:value"]),
        line_number=8,
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
    )

    assert result.query_id == "bad-identifier"
    assert result.status == "input_invalid"
    assert result.error is not None
    assert result.error.code == "invalid_record"
    assert "Unknown identifier type" in result.error.message
    assessor.evaluate_supplied.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line",
    [
        pytest.param("[]", id="non-object"),
        pytest.param('{"query_id": 42}', id="non-string-query-id"),
    ],
)
async def test_evaluate_line_records_uncorrelatable_schema_failure(line):
    """Invalid object shapes still produce an envelope without a false query key."""
    assessor = AsyncMock()
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    result = await runner.evaluate_line(
        run_id=uuid7(),
        line=line,
        line_number=9,
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
    )

    assert result.query_id is None
    assert result.status == "input_invalid"
    assert result.error is not None
    assert result.error.code == "invalid_record"
    assessor.evaluate_supplied.assert_not_awaited()


@pytest.mark.asyncio
async def test_evaluate_lines_records_assessor_failure_and_continues():
    """A retrieval, hydration or scoring failure must remain local to its record."""
    call_count = 0

    async def assess(incoming, _selection, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            msg = "candidate hydration failed"
            raise DeduplicationError(msg)
        return _assessment(incoming.id)

    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = assess
    runner = DeduplicationEvaluationRunner(assessor=assessor)
    lines = AsyncMock()
    lines.__aiter__.return_value = [
        _valid_line("first"),
        _valid_line("failed"),
        _valid_line("last"),
    ]

    results = [
        result
        async for result in runner.evaluate_lines(
            run_id=uuid7(),
            lines=lines,
            retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
            k=10,
        )
    ]

    assert [result.status for result in results] == [
        "assessed",
        "evaluation_failed",
        "assessed",
    ]
    failed = results[1]
    assert failed.query_id == "failed"
    assert failed.incoming_reference_id is not None
    assert failed.assessment is None
    assert failed.error is not None
    assert failed.error.code == "evaluation_failed"
    assert failed.error.message == (
        "Evaluation failed (DeduplicationError): candidate hydration failed"
    )
    assert assessor.evaluate_supplied.await_count == 3


@pytest.mark.asyncio
async def test_evaluate_line_propagates_unexpected_assessor_failure():
    """Systemic failures and programming errors must fail the run."""
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = ValueError("unexpected scorer defect")
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    with pytest.raises(ValueError, match="unexpected scorer defect"):
        await runner.evaluate_line(
            run_id=uuid7(),
            line=_valid_line("unexpected-failure"),
            line_number=1,
            retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
            k=10,
        )


@pytest.mark.asyncio
async def test_evaluate_line_does_not_turn_cancellation_into_a_record_failure():
    """Run cancellation must still stop evaluation immediately."""
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = asyncio.CancelledError
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    with pytest.raises(asyncio.CancelledError):
        await runner.evaluate_line(
            run_id=uuid7(),
            line=_valid_line("cancelled"),
            line_number=1,
            retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
            k=10,
        )


@pytest.mark.asyncio
async def test_project_pair_results_preserves_correlation_routes_and_evidence():
    """Pair rows are a pure projection of the completed assessment."""
    es_candidate_id = uuid7()
    identifier_candidate_id = uuid7()
    candidates = [
        ScoredDeduplicationCandidate(
            candidate=Candidate(
                reference_id=es_candidate_id,
                rank=1,
                routes=[
                    CandidateElasticsearchRoute(
                        policy="candidate_selection_v1",
                        rank=2,
                        score=8.5,
                    )
                ],
            ),
            pair_result=DeduplicationPairResult(
                probability=0.91,
                field_comparisons={
                    "title": DeduplicationFieldComparison(
                        incoming_value="A study",
                        candidate_value="A Study",
                        status=DeduplicationFieldStatus.MATCH,
                        score=0.98,
                    )
                },
                suggested_label="duplicate",
            ),
            clears_threshold=True,
        ),
        ScoredDeduplicationCandidate(
            candidate=Candidate(
                reference_id=identifier_candidate_id,
                rank=2,
                routes=[
                    CandidateIdentifierRoute(
                        matched_identifiers=[
                            CandidateIdentifier(
                                identifier="W1",
                                identifier_type=ExternalIdentifierType.OPEN_ALEX,
                            )
                        ]
                    )
                ],
            ),
            pair_result=DeduplicationPairResult(
                unscorable_reason="insufficient comparable fields"
            ),
            clears_threshold=None,
        ),
    ]
    assessor = AsyncMock()

    def assess(incoming, _selection, **_kwargs):
        assessment = _assessment(incoming.id)
        return assessment.model_copy(
            update={
                "candidate_selection": assessment.candidate_selection.model_copy(
                    update={"candidates": [item.candidate for item in candidates]}
                ),
                "scored_candidates": candidates,
                "unscorable_candidate_ids": [identifier_candidate_id],
            }
        )

    assessor.evaluate_supplied.side_effect = assess
    runner = DeduplicationEvaluationRunner(assessor=assessor)
    record_result = await runner.evaluate_line(
        run_id=uuid7(),
        line=_valid_line("pair-projection"),
        line_number=42,
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
    )

    pair_results = runner.project_pair_results(record_result)

    incoming_reference_id = cast(UUID, record_result.incoming_reference_id)
    assert pair_results == [
        EvaluationPairResult(
            run_id=record_result.run_id,
            query_id="pair-projection",
            line_number=42,
            incoming_reference_id=incoming_reference_id,
            candidate_reference_id=item.candidate.reference_id,
            retrieval_rank=item.candidate.rank,
            retrieval_routes=item.candidate.routes,
            pair_result=item.pair_result,
            threshold=0.85,
            clears_threshold=item.clears_threshold,
        )
        for item in candidates
    ]
    assessor.evaluate_supplied.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_pair_results_ignores_non_assessed_record():
    """Input failures do not contribute rows to the pair artifact."""
    assessor = AsyncMock()
    runner = DeduplicationEvaluationRunner(assessor=assessor)
    record_result = await runner.evaluate_line(
        run_id=uuid7(),
        line="not json",
        line_number=7,
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        k=10,
    )

    assert runner.project_pair_results(record_result) == []
    assessor.evaluate_supplied.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_preserves_input_and_writes_complete_bundle(monkeypatch):
    """A blob run hashes exact input bytes and writes its completion marker last."""
    run_id = uuid7()
    input_file = BlobStorageFile.from_uri(
        "azure://dedup-evals/datasets/retrieval-query-set/v1/records.jsonl"
    )
    source_bytes = (_valid_line("assessed") + "\nnot json").encode()
    chunks = AsyncMock()
    chunks.__aiter__.return_value = [source_bytes[:17], source_bytes[17:]]
    client = MagicMock()
    client.stream_chunks.return_value = chunks
    blob_repository = BlobRepository()
    monkeypatch.setattr(
        blob_repository, "_preload_config", AsyncMock(return_value=client)
    )
    uploaded: dict[str, bytes] = {}
    upload_order: list[str] = []

    async def upload(content, path, filename, **_kwargs):
        assert isinstance(content, BytesIO)
        uploaded[filename] = content.getvalue()
        upload_order.append(filename)
        return BlobStorageFile(
            location=BlobStorageLocation.MINIO,
            container="test",
            path=path,
            filename=filename,
        )

    blob_repository.upload_file_to_blob_storage = AsyncMock(side_effect=upload)
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, *_args, **_kwargs: (
        _assessment_with_pair_evidence(incoming.id, _kwargs["retrieval_policy"])
    )
    runner = DeduplicationEvaluationRunner(assessor=assessor)
    configuration = _run_configuration()

    artifacts = await runner.run(
        run_id=run_id,
        input_file=input_file,
        blob_repository=blob_repository,
        configuration=configuration,
    )

    input_sha256 = hashlib.sha256(source_bytes).hexdigest()
    assert (
        artifacts.run_id,
        artifacts.input_file,
        artifacts.input_byte_size,
        artifacts.input_sha256,
    ) == (
        run_id,
        input_file,
        len(source_bytes),
        input_sha256,
    )
    assert upload_order == [
        "record-results.jsonl",
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
    } == {filename: f"deduplication_evaluation/{run_id}" for filename in uploaded}
    record_rows = [
        json.loads(line) for line in uploaded["record-results.jsonl"].splitlines()
    ]
    assert [row["status"] for row in record_rows] == ["assessed", "input_invalid"]
    assert (
        record_rows[0]["assessment"]["candidate_selection"]["retrieval_policy"]
        == configuration.retrieval_policy
    )
    pair_rows = [
        json.loads(line) for line in uploaded["pair-results.jsonl"].splitlines()
    ]
    assert [row["clears_threshold"] for row in pair_rows] == [True, False, None]
    expected_summary = (
        "# Deduplication evaluation summary\n\n"
        f"Run ID: `{run_id}`\n\n"
        f"Input: `{input_file.to_uri()}`\n\n"
        f"Input bytes: {len(source_bytes)}\n\n"
        f"Input SHA-256: `{input_sha256}`\n\n"
        "Records: 2\n\n"
        "Assessed records: 1\n\n"
        "Invalid input records: 1\n\n"
        "Evaluation-failed records: 0\n\n"
        "Pair rows: 3\n\n"
        "## Assessment outcomes\n\n"
        "- `propose_canonical`: 0\n"
        "- `propose_duplicate`: 0\n"
        "- `no_proposal`: 1\n\n"
        "## Pair evidence\n\n"
        "- Clears threshold: 1\n"
        "- Below threshold: 1\n"
        "- Unscorable: 1\n"
    )
    assert uploaded["summary.md"].decode() == expected_summary
    assert json.loads(uploaded["manifest.json"]) == {
        "schema_version": "deduplication-evaluation-manifest/v1",
        "run_id": str(run_id),
        "input": {
            "uri": input_file.to_uri(),
            "dataset_version": "retrieval-query-set/v1",
            "byte_size": len(source_bytes),
            "sha256": input_sha256,
        },
        "configuration": configuration.model_dump(mode="json"),
        "counts": {
            "record_statuses": {
                "assessed": 1,
                "input_invalid": 1,
                "evaluation_failed": 0,
            },
            "pair_rows": 3,
        },
        "artifacts": {
            "record-results.jsonl": _expected_artifact(
                artifacts.record_results_file,
                uploaded["record-results.jsonl"],
                "evaluation-record-result/v1",
            ),
            "pair-results.jsonl": _expected_artifact(
                artifacts.pair_results_file,
                uploaded["pair-results.jsonl"],
                "evaluation-pair-result/v1",
            ),
            "summary.md": _expected_artifact(
                artifacts.summary_file,
                uploaded["summary.md"],
                "deduplication-evaluation-summary/v1",
            ),
        },
    }
    client.stream_chunks.assert_called_once_with(input_file)
    assessor.evaluate_supplied.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_checks_artifact_writability_before_evaluation():
    """A stable output failure is reported before spending work on evaluation."""
    run_id = uuid7()
    input_file = BlobStorageFile.from_uri(
        "azure://dedup-evals/datasets/retrieval-query-set/v1/records.jsonl"
    )
    chunks = AsyncMock()
    chunks.__aiter__.return_value = [_valid_line("unused").encode()]
    blob_repository = MagicMock(spec=BlobRepository)
    blob_repository.stream_chunks_from_blob_storage.return_value = chunks
    error = BlobStorageError("result prefix is not writable")
    blob_repository.upload_file_to_blob_storage = AsyncMock(side_effect=error)
    assessor = AsyncMock()
    assessor.evaluate_supplied.side_effect = lambda incoming, *_args, **_kwargs: (
        _assessment(incoming.id)
    )
    runner = DeduplicationEvaluationRunner(assessor=assessor)

    with pytest.raises(BlobStorageError, match="result prefix is not writable"):
        await runner.run(
            run_id=run_id,
            input_file=input_file,
            blob_repository=blob_repository,
            configuration=_run_configuration(),
        )

    blob_repository.stream_chunks_from_blob_storage.assert_not_called()
    assessor.evaluate_supplied.assert_not_awaited()
    preflight = blob_repository.upload_file_to_blob_storage.await_args.kwargs
    assert preflight["content"].getvalue() == b""
    assert {key: value for key, value in preflight.items() if key != "content"} == {
        "path": f"deduplication_evaluation/{run_id}",
        "filename": "record-results.jsonl",
        "content_type": "application/jsonl",
    }
