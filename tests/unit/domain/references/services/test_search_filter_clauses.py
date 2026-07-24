"""Unit tests for structured filter clause building in ReferenceESRepository."""

from elasticsearch.dsl.query import Prefix, Range, Term, Terms

from app.domain.references.models.models import (
    AnnotationFilter,
    FacetType,
    LinkedDataConceptFilter,
    PublicationYearRange,
    SearchQuery,
)
from app.domain.references.repository import ReferenceESRepository


class _StubReferenceESRepository(ReferenceESRepository):
    """ReferenceESRepository without an ES client, for testing pure clause builders."""

    def __init__(self) -> None:
        pass


def test_publication_year_range_both_bounds():
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020, end=2022),
        ),
    )
    assert clauses == [Range(publication_year={"gte": 2020, "lte": 2022})]


def test_publication_year_range_start_only():
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020),
        ),
    )
    assert clauses == [Range(publication_year={"gte": 2020})]


def test_annotation_filter_scheme_and_label_uses_term_query():
    """Scheme/label combos resolve to an exact ``Term`` on the keyword field."""
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            annotation_filters=[
                AnnotationFilter(scheme="test", label='unescaped"quote'),
            ],
        ),
    )
    assert clauses == [Term(annotations='test/unescaped"quote')]


def test_annotation_filter_scheme_only_uses_prefix_query():
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            annotation_filters=[AnnotationFilter(scheme="inclusion:destiny")],
        ),
    )
    assert clauses == [Prefix(annotations="inclusion:destiny/")]


def test_linked_data_concept_filter_uses_terms_query():
    """Concept filters resolve to a single ``terms`` clause (OR-of-URIs)."""
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            linked_data_concept_filters=[
                LinkedDataConceptFilter(
                    concept_uris=[
                        "https://vocab.example.org/A",
                        "https://vocab.example.org/B",
                    ],
                ),
            ],
        ),
    )
    assert clauses == [
        Terms(
            linked_data_concepts=[
                "https://vocab.example.org/A",
                "https://vocab.example.org/B",
            ],
        )
    ]


def test_multiple_concept_filters_produce_multiple_clauses():
    """Each repeated concept= maps to its own ``Terms`` clause (ANDed at the bool)."""
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            linked_data_concept_filters=[
                LinkedDataConceptFilter(concept_uris=["https://vocab.example.org/A"]),
                LinkedDataConceptFilter(
                    concept_uris=[
                        "https://vocab.example.org/B",
                        "https://vocab.example.org/C",
                    ],
                ),
            ],
        ),
    )
    assert clauses == [
        Terms(linked_data_concepts=["https://vocab.example.org/A"]),
        Terms(
            linked_data_concepts=[
                "https://vocab.example.org/B",
                "https://vocab.example.org/C",
            ],
        ),
    ]


def test_annotation_filter_score_uses_range_query_on_dynamic_field():
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            annotation_filters=[
                AnnotationFilter(scheme="inclusion:destiny", score=0.8),
            ],
        ),
    )
    assert clauses == [Range(inclusion_destiny={"gte": 0.8})]


def test_no_filters_yields_empty_list():
    repository = _StubReferenceESRepository()
    assert repository._build_filter_clauses(SearchQuery(query_string="*")) == []  # noqa: SLF001


def test_filters_combined_in_declaration_order():
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020),
            annotation_filters=[
                AnnotationFilter(scheme="inclusion:destiny", score=0.5),
                AnnotationFilter(scheme="taxonomy:exposure", label="Heat"),
            ],
        ),
    )
    assert clauses == [
        Range(publication_year={"gte": 2020}),
        Range(inclusion_destiny={"gte": 0.5}),
        Term(annotations="taxonomy:exposure/Heat"),
    ]


def test_build_filter_clauses_excludes_named_facet_filters():
    """The sibling-aware path passes ``exclude_facet`` to drop that facet's filters."""
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020),
            annotation_filters=[AnnotationFilter(scheme="taxonomy:x", label="y")],
            linked_data_concept_filters=[
                LinkedDataConceptFilter(concept_uris=["urn:a"]),
            ],
        ),
        exclude_facet=FacetType.CONCEPTS,
    )
    assert clauses == [
        Range(publication_year={"gte": 2020}),
        Term(annotations="taxonomy:x/y"),
    ]


def test_normalize_sort_key_bare_relevance_is_best_first():
    """Bare ``relevance`` maps to ``_score`` descending (best matches first)."""
    repository = _StubReferenceESRepository()
    assert repository._normalize_sort_key("relevance") == {  # noqa: SLF001
        "_score": {"order": "desc"}
    }


def test_normalize_sort_key_descending_relevance_is_worst_first():
    """``-relevance`` inverts to ``_score`` ascending (worst matches first)."""
    repository = _StubReferenceESRepository()
    assert repository._normalize_sort_key("-relevance") == {  # noqa: SLF001
        "_score": {"order": "asc"}
    }


def test_normalize_sort_key_plus_relevance_is_best_first():
    """A leading ``+`` is stripped but does not invert the best-first default."""
    repository = _StubReferenceESRepository()
    assert repository._normalize_sort_key("+relevance") == {  # noqa: SLF001
        "_score": {"order": "desc"}
    }


def test_normalize_sort_key_passes_mapped_fields_through_unchanged():
    """Non-``relevance`` tokens are returned verbatim for ES to resolve."""
    repository = _StubReferenceESRepository()
    assert repository._normalize_sort_key("year") == "year"  # noqa: SLF001
    assert repository._normalize_sort_key("-year") == "-year"  # noqa: SLF001
    # A field that merely contains "relevance" is not the virtual token.
    assert repository._normalize_sort_key("relevance_score") == "relevance_score"  # noqa: SLF001
