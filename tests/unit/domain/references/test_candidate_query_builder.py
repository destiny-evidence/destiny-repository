# ruff: noqa: SLF001
"""Tests for the candidate query builder's year-clause seam.

Tests exercise the repository's private query-builder helpers directly.
"""

from unittest.mock import MagicMock

from app.core.config import DedupCandidateScoringConfig
from app.domain.references.models.models import CandidateCanonicalSearchFields
from app.domain.references.models.retrieval_policy import YearStrategy
from app.domain.references.repository import ReferenceESRepository


def test_hard_window_builds_pm1_year_range():
    clauses = ReferenceESRepository._year_filter_clauses(2000, YearStrategy.HARD_WINDOW)
    assert len(clauses) == 1
    assert clauses[0].to_dict()["range"]["publication_year"] == {
        "gte": 1999,
        "lte": 2001,
    }


def test_no_filter_yields_no_year_clause():
    assert (
        ReferenceESRepository._year_filter_clauses(2000, YearStrategy.NO_FILTER) == []
    )


def test_hard_window_without_year_yields_no_clause():
    assert (
        ReferenceESRepository._year_filter_clauses(None, YearStrategy.HARD_WINDOW) == []
    )


def test_build_candidate_query_canonical_unconditional():
    """Canonical filter present for every strategy; only the year range varies."""
    repo = ReferenceESRepository(client=MagicMock())
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["Smith"], publication_year=2000
    )
    for strategy in (YearStrategy.HARD_WINDOW, YearStrategy.NO_FILTER):
        query = repo._build_candidate_query(
            fields,
            scoring_config=DedupCandidateScoringConfig(),
            year_strategy=strategy,
            reference_id=None,
        )
        filter_dicts = [clause.to_dict() for clause in query.filter]
        assert any(
            "term" in fd and "duplicate_determination" in fd["term"]
            for fd in filter_dicts
        )
        has_year_range = any(
            "range" in fd and "publication_year" in fd["range"] for fd in filter_dicts
        )
        assert has_year_range is (strategy is YearStrategy.HARD_WINDOW)
