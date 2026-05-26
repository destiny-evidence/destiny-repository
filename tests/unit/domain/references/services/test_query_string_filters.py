"""Unit tests for structured filter clause building in SearchService."""

from elasticsearch.dsl.query import Prefix, Range, Term, Terms

from app.domain.references.models.models import (
    AnnotationFilter,
    LinkedDataConceptFilter,
    PublicationYearRange,
    SearchQuery,
)
from app.domain.references.services.search_service import SearchService


class _StubSearchService(SearchService):
    """SearchService without dependencies, for testing filter builders."""

    def __init__(self) -> None:
        pass


def test_publication_year_range_both_bounds():
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020, end=2022),
        ),
    )
    assert clauses == [Range(publication_year={"gte": 2020, "lte": 2022})]


def test_publication_year_range_start_only():
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020),
        ),
    )
    assert clauses == [Range(publication_year={"gte": 2020})]


def test_annotation_filter_scheme_and_label_uses_term_query():
    """Scheme/label combos resolve to an exact ``Term`` on the keyword field.

    No Lucene escaping involved: special characters in the label go through the
    DSL serializer untouched.
    """
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            annotation_filters=[
                AnnotationFilter(scheme="test", label='unescaped"quote'),
            ],
        ),
    )
    assert clauses == [Term(annotations='test/unescaped"quote')]


def test_annotation_filter_scheme_only_uses_prefix_query():
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            annotation_filters=[AnnotationFilter(scheme="inclusion:destiny")],
        ),
    )
    assert clauses == [Prefix(annotations="inclusion:destiny/")]


def test_linked_data_concept_filter_uses_terms_query():
    """Concept filters resolve to a single ``terms`` clause (OR-of-URIs)."""
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
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
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
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
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            annotation_filters=[
                AnnotationFilter(scheme="inclusion:destiny", score=0.8),
            ],
        ),
    )
    assert clauses == [Range(inclusion_destiny={"gte": 0.8})]


def test_no_filters_yields_empty_list():
    service = _StubSearchService()
    assert service._build_filter_clauses(SearchQuery(query_string="*")) == []  # noqa: SLF001


def test_filters_combined_in_declaration_order():
    service = _StubSearchService()
    clauses = service._build_filter_clauses(  # noqa: SLF001
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
