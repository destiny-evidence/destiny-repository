# ruff: noqa: SLF001
"""Tests for service query construction and Elasticsearch translation."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from app.core.config import DedupCandidateScoringConfig
from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
    DuplicateDetermination,
    RetrievalPolicyName,
)
from app.domain.references.models.retrieval_policy import resolve_retrieval_policy
from app.domain.references.repository import ReferenceESRepository
from app.domain.references.services.deduplication_service import (
    build_candidate_canonical_search_query,
)


def _query(
    fields: CandidateCanonicalSearchFields,
    policy_name: RetrievalPolicyName,
    *,
    reference_id: UUID | None = None,
):
    return build_candidate_canonical_search_query(
        fields,
        scoring_config=DedupCandidateScoringConfig(),
        policy=resolve_retrieval_policy(policy_name),
        reference_id=reference_id,
    )


def test_hard_window_builds_pm1_year_range():
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["Smith"], publication_year=2000
    )
    query = _query(fields, RetrievalPolicyName.CURRENT_FUZZY_V1)
    assert query.publication_year_range == (1999, 2001)


def test_no_filter_yields_no_year_clause():
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["Smith"], publication_year=2000
    )
    query = _query(fields, RetrievalPolicyName.NO_YEAR_FILTER_V1)
    assert query.publication_year_range is None


def test_hard_window_without_year_yields_no_clause():
    fields = CandidateCanonicalSearchFields(title="Shared Title", authors=["Smith"])
    query = _query(fields, RetrievalPolicyName.CURRENT_FUZZY_V1)
    assert query.publication_year_range is None


def test_hard_window_with_year_zero_yields_no_clause():
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["Smith"], publication_year=0
    )
    query = _query(fields, RetrievalPolicyName.CURRENT_FUZZY_V1)
    assert query.publication_year_range is None


def test_builder_rejects_missing_title():
    fields = CandidateCanonicalSearchFields(authors=["Smith"], publication_year=2000)

    with pytest.raises(DeduplicationValueError, match="requires a title"):
        _query(fields, RetrievalPolicyName.CURRENT_FUZZY_V1)


def test_service_builds_complete_query_regime():
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["G Smith"], publication_year=2000
    )
    query = _query(fields, RetrievalPolicyName.CURRENT_FUZZY_V1)
    assert query.title == "Shared Title"
    assert query.title_fuzziness == "AUTO"
    assert query.title_boost == 2.0
    assert query.title_minimum_should_match == "50%"
    assert query.author_terms == ("Smith",)
    assert query.author_tie_breaker == 0.1
    assert query.duplicate_determination.value == "canonical"


def test_build_candidate_query_canonical_unconditional():
    """Canonical filter present for every strategy; only the year range varies."""
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["Smith"], publication_year=2000
    )
    repo = ReferenceESRepository(client=MagicMock())
    for policy_name in (
        RetrievalPolicyName.CURRENT_FUZZY_V1,
        RetrievalPolicyName.NO_YEAR_FILTER_V1,
    ):
        query = repo._to_es_candidate_query(_query(fields, policy_name))
        filter_dicts = [clause.to_dict() for clause in query.filter]
        assert any(
            "term" in fd and "duplicate_determination" in fd["term"]
            for fd in filter_dicts
        )
        has_year_range = any(
            "range" in fd and "publication_year" in fd["range"] for fd in filter_dicts
        )
        assert has_year_range is (policy_name is RetrievalPolicyName.CURRENT_FUZZY_V1)


def test_es_translation_preserves_baseline_query_semantics():
    reference_id = UUID("00000000-0000-0000-0000-000000000001")
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["G Smith"], publication_year=2000
    )
    query = _query(
        fields,
        RetrievalPolicyName.CURRENT_FUZZY_V1,
        reference_id=reference_id,
    )

    assert ReferenceESRepository._to_es_candidate_query(query).to_dict() == {
        "bool": {
            "must": [
                {
                    "match": {
                        "title": {
                            "query": "Shared Title",
                            "fuzziness": "AUTO",
                            "boost": 2.0,
                            "operator": "or",
                            "minimum_should_match": "50%",
                        }
                    }
                }
            ],
            "should": [
                {
                    "dis_max": {
                        "queries": [{"match": {"authors": "Smith"}}],
                        "tie_breaker": 0.1,
                    }
                }
            ],
            "filter": [
                {
                    "range": {
                        "publication_year": {
                            "gte": 1999,
                            "lte": 2001,
                        }
                    }
                },
                {"term": {"duplicate_determination": DuplicateDetermination.CANONICAL}},
            ],
            "must_not": [{"ids": {"values": [reference_id]}}],
        }
    }


def test_soft_decay_builds_decay_spec_and_no_range():
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["Smith"], publication_year=2000
    )
    query = _query(fields, RetrievalPolicyName.SOFT_YEAR_DECAY_V1)
    assert query.publication_year_range is None
    decay = query.publication_year_decay
    assert decay is not None
    assert (decay.origin, decay.offset, decay.scale, decay.decay, decay.weight) == (
        2000,
        1,
        9,
        0.5,
        0.10,
    )
    assert decay.max_boost == pytest.approx(1.10)


def test_soft_decay_without_year_raises():
    fields = CandidateCanonicalSearchFields(title="Shared Title", authors=["Smith"])
    with pytest.raises(DeduplicationValueError, match="publication year"):
        _query(fields, RetrievalPolicyName.SOFT_YEAR_DECAY_V1)


def test_soft_decay_es_translation_wraps_function_score():
    reference_id = UUID("00000000-0000-0000-0000-000000000001")
    fields = CandidateCanonicalSearchFields(
        title="Shared Title", authors=["G Smith"], publication_year=2000
    )
    query = _query(
        fields,
        RetrievalPolicyName.SOFT_YEAR_DECAY_V1,
        reference_id=reference_id,
    )

    assert ReferenceESRepository._to_es_candidate_query(query).to_dict() == {
        "function_score": {
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "title": {
                                    "query": "Shared Title",
                                    "fuzziness": "AUTO",
                                    "boost": 2.0,
                                    "operator": "or",
                                    "minimum_should_match": "50%",
                                }
                            }
                        }
                    ],
                    "should": [
                        {
                            "dis_max": {
                                "queries": [{"match": {"authors": "Smith"}}],
                                "tie_breaker": 0.1,
                            }
                        }
                    ],
                    "filter": [
                        {
                            "term": {
                                "duplicate_determination": (
                                    DuplicateDetermination.CANONICAL
                                )
                            }
                        }
                    ],
                    "must_not": [{"ids": {"values": [reference_id]}}],
                }
            },
            "functions": [
                {"weight": 1.0},
                {
                    "filter": {"exists": {"field": "publication_year"}},
                    "exp": {
                        "publication_year": {
                            "origin": 2000,
                            "offset": 1,
                            "scale": 9,
                            "decay": 0.5,
                        }
                    },
                    "weight": 0.1,
                },
            ],
            "score_mode": "sum",
            "boost_mode": "multiply",
            "max_boost": 1.1,
        }
    }
