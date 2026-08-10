"""Tests for the deduplication evaluation runner."""

from unittest.mock import AsyncMock
from uuid import uuid7

import pytest

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
    assert result.incoming_reference_id.version == 7
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
