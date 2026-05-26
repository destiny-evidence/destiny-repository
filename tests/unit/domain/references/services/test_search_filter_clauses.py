"""Unit tests for structured filter clause building in ReferenceESRepository."""

import pytest
from elasticsearch.dsl.query import Prefix, Range, Term, Terms

from app.core.exceptions import ESQueryError
from app.domain.references.models.models import (
    AnnotationFilter,
    ConceptSiblingGroup,
    FacetType,
    LinkedDataConceptFilter,
    PublicationYearRange,
    SearchQuery,
    SiblingGrouping,
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


def test_filter_clauses_excluding_concepts_omits_concept_filters_only():
    """Sibling-aware path uses this to leave concept filters for post_filter only."""
    repository = _StubReferenceESRepository()
    clauses = repository._build_filter_clauses_excluding_concepts(  # noqa: SLF001
        SearchQuery(
            query_string="*",
            publication_year_range=PublicationYearRange(start=2020),
            annotation_filters=[AnnotationFilter(scheme="taxonomy:x", label="y")],
            linked_data_concept_filters=[
                LinkedDataConceptFilter(concept_uris=["urn:a"]),
            ],
        ),
    )
    assert clauses == [
        Range(publication_year={"gte": 2020}),
        Term(annotations="taxonomy:x/y"),
    ]


# ---- _build_grouped_facet_aggs ---------------------------------------------------


_FIELD = "linked_data_concepts"
_MAX_BUCKETS = 1000

BOTANY = "urn:Botany"
ZOOLOGY = "urn:Zoology"
MICROBIOLOGY = "urn:Microbiology"
AFRICA = "urn:Africa"
ASIA = "urn:Asia"
EUROPE = "urn:Europe"


def _topics_group() -> ConceptSiblingGroup:
    return ConceptSiblingGroup(
        source_filter=LinkedDataConceptFilter(concept_uris=[BOTANY, ZOOLOGY]),
        siblings_including_selected=frozenset({BOTANY, ZOOLOGY, MICROBIOLOGY}),
    )


def _region_group() -> ConceptSiblingGroup:
    return ConceptSiblingGroup(
        source_filter=LinkedDataConceptFilter(concept_uris=[AFRICA]),
        siblings_including_selected=frozenset({AFRICA, ASIA, EUROPE}),
    )


def _worked_example_grouping() -> SiblingGrouping:
    topics, region = _topics_group(), _region_group()
    return SiblingGrouping(
        groups=(topics, region),
        all_grouped_uris=topics.siblings_including_selected
        | region.siblings_including_selected,
    )


def test_grouped_facet_aggs_match_ticket_worked_example():
    """Per-group filter uses *other* groups' selected URIs; include is the full group."""  # noqa: E501
    repository = _StubReferenceESRepository()
    grouping = _worked_example_grouping()
    aggs = repository._build_grouped_facet_aggs(  # noqa: SLF001
        _FIELD, grouping, max_buckets=_MAX_BUCKETS
    )
    assert [spec.name for spec in aggs] == [
        "facet_group_0",
        "facet_group_1",
        "unselected",
    ]
    group_0, group_1, unselected = aggs

    # facet_group_0 is the Topics group: filter is Region's selection ([AFRICA]).
    assert group_0.field == _FIELD
    assert group_0.filter_clauses == (Terms(linked_data_concepts=[AFRICA]),)
    assert group_0.include == (BOTANY, MICROBIOLOGY, ZOOLOGY)  # sorted
    assert group_0.exclude is None
    assert group_0.min_doc_count == 0
    assert group_0.size == 3

    # facet_group_1 is Region: filter is Topics' selection ([BOTANY, ZOOLOGY]).
    assert group_1.filter_clauses == (Terms(linked_data_concepts=[BOTANY, ZOOLOGY]),)
    assert group_1.include == (AFRICA, ASIA, EUROPE)
    assert group_1.min_doc_count == 0

    # unselected: filter is all groups' selections; exclude all known URIs.
    assert unselected.filter_clauses == (
        Terms(linked_data_concepts=[BOTANY, ZOOLOGY]),
        Terms(linked_data_concepts=[AFRICA]),
    )
    assert unselected.exclude == (AFRICA, ASIA, BOTANY, EUROPE, MICROBIOLOGY, ZOOLOGY)
    assert unselected.include is None
    assert unselected.min_doc_count == 1
    assert unselected.size == _MAX_BUCKETS


def test_grouped_facet_aggs_bucket_universes_are_disjoint():
    """Each URI must appear in at most one agg spec's include/exclude set."""
    repository = _StubReferenceESRepository()
    grouping = _worked_example_grouping()
    aggs = repository._build_grouped_facet_aggs(  # noqa: SLF001
        _FIELD, grouping, max_buckets=_MAX_BUCKETS
    )
    universes: list[set[str]] = [
        set(spec.include) for spec in aggs if spec.include is not None
    ]
    # facet_group_N includes overlap is disallowed.
    for i, universe in enumerate(universes):
        for other in universes[i + 1 :]:
            assert universe.isdisjoint(other)


def test_validate_grouping_against_max_buckets_raises_when_exceeded():
    """A group with more siblings than max_buckets must surface loudly."""
    huge_group = ConceptSiblingGroup(
        source_filter=LinkedDataConceptFilter(concept_uris=[BOTANY]),
        siblings_including_selected=frozenset({f"urn:concept:{i}" for i in range(5)}),
    )
    grouping = SiblingGrouping(
        groups=(huge_group,), all_grouped_uris=huge_group.siblings_including_selected
    )
    with pytest.raises(ESQueryError, match="exceeding max_buckets"):
        ReferenceESRepository._validate_grouping_against_max_buckets(  # noqa: SLF001
            grouping, max_buckets=3
        )


def test_validate_grouping_against_max_buckets_ok_when_within_limit():
    """Equal-to-limit is fine."""
    grouping = _worked_example_grouping()
    # No raise.
    ReferenceESRepository._validate_grouping_against_max_buckets(  # noqa: SLF001
        grouping, max_buckets=3
    )


# A bucket-uniqueness sanity check anchored to the FacetType enum so we
# don't regress on the contract "every URI appears at most once in the
# flattened response".
def test_aggregate_facets_facet_type_is_concepts_only_today():
    assert tuple(FacetType) == (FacetType.CONCEPTS,)
