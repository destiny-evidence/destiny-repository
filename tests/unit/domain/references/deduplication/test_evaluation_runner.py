"""Tests for the deduplication evaluation runner."""

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest

from app.core.exceptions import DeduplicationError
from app.domain.references.models.models import (
    CandidateSelectionDiagnostics,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    ExternalIdentifierType,
    InputSearchability,
    RetrievalPolicyName,
)
from app.domain.references.services.deduplication_evaluation_runner import (
    DeduplicationEvaluationRunner,
    EvaluationRecordStatus,
)


def _assessment(incoming_reference_id):
    return DeduplicationAssessment(
        incoming_reference_id=incoming_reference_id,
        candidate_selection=CandidateSelectionResult(
            retrieval_policy=(RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1),
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
        _assessment(incoming.id)
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

    assert result.run_id == run_id
    assert result.query_id == "oa-km:W1:W2"
    assert result.line_number == 42
    assert result.status == EvaluationRecordStatus.ASSESSED
    assert result.incoming_reference_id is not None
    assert result.incoming_reference_id.version == 7
    assert result.assessment is not None
    assert result.assessment == _assessment(result.incoming_reference_id)
    assert result.error is None
    incoming, selection = assessor.evaluate_supplied.await_args.args
    assert incoming.id == result.incoming_reference_id
    assert incoming.visibility == "public"
    assert incoming.identifiers[0].identifier_type == ExternalIdentifierType.OPEN_ALEX
    assert incoming.identifiers[0].identifier == "W1"
    assert incoming.enhancements[0].source == "retrieval-query-set/v1"
    biblio = incoming.enhancements[0].content
    assert biblio.title == "A yearless study"
    assert biblio.publication_year is None
    assert [author.display_name for author in biblio.authorship] == [
        "First Author",
        "Middle Author",
        "Last Author",
    ]
    assert [author.position for author in biblio.authorship] == [
        "first",
        "middle",
        "last",
    ]
    assert selection.title == "A yearless study"
    assert selection.authors == ["First Author", "Middle Author", "Last Author"]
    assert selection.publication_year is None
    assert selection.excluded_reference_id == held_reference_id
    assert selection.identifiers[0].identifier_type == ExternalIdentifierType.OPEN_ALEX
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
        retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
            retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
        retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
        retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
        retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
            retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
            retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
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
            retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
            k=10,
        )
