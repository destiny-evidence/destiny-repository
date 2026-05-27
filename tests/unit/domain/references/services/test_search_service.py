"""Integration tests for search service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from elasticsearch import AsyncElasticsearch
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SiblingGroupingError
from app.domain.references.models.models import (
    AnnotationFilter,
    FacetType,
    LinkedDataConceptFilter,
    PublicationYearRange,
    SearchQuery,
    SiblingGroup,
)
from app.domain.references.repository import ReferenceESRepository
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.search_service import SearchService
from app.external.vocabulary.client import VocabularyArtifactClient
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import (
    AbstractContentEnhancementFactory,
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    BooleanAnnotationFactory,
    EnhancementFactory,
    ReferenceFactory,
    to_indexable,
)


@pytest.fixture
async def es_reference_repository(
    es_client: AsyncElasticsearch,
) -> ReferenceESRepository:
    """Fixture to create an Elasticsearch reference repository."""
    return ReferenceESRepository(
        client=es_client,
    )


@pytest.fixture
async def search_service(
    es_client: AsyncElasticsearch,
    session: AsyncSession,
    es_reference_repository: ReferenceESRepository,
) -> SearchService:
    """Fixture to create a search service with ES and SQL unit of work."""
    blob_repo = BlobRepository()
    anti_corruption_service = ReferenceAntiCorruptionService(blob_repo.get_signed_url)
    es_uow = AsyncESUnitOfWork(es_client)
    es_uow._is_active = True  # noqa: SLF001
    es_uow.references = es_reference_repository
    sql_uow = AsyncSqlUnitOfWork(session)

    vocab_client = MagicMock(spec=VocabularyArtifactClient)

    return SearchService(
        anti_corruption_service=anti_corruption_service,
        sql_uow=sql_uow,
        es_uow=es_uow,
        vocab_client=vocab_client,
    )


async def test_search_with_query_string_publication_year_filter(
    search_service: SearchService,
    es_reference_repository: ReferenceESRepository,
):
    """Test searching with publication year range filters results correctly."""
    # Create references with different publication years
    ref_2020 = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Test Paper Alpha",
                    publication_year=2020,
                )
            )
        ]
    )

    ref_2022 = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Test Paper Beta",
                    publication_year=2022,
                )
            ),
            EnhancementFactory.build(
                content=AbstractContentEnhancementFactory.build(
                    abstract="This is an abstract. Dugong."
                )
            ),
        ]
    )

    ref_2024 = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Test Paper Gamma",
                    publication_year=2024,
                )
            ),
            EnhancementFactory.build(
                content=AbstractContentEnhancementFactory.build(
                    abstract="This is an abstract. Dugong."
                )
            ),
        ]
    )

    # Add references to ES
    await es_reference_repository.add(to_indexable(ref_2020))
    await es_reference_repository.add(to_indexable(ref_2022))
    await es_reference_repository.add(to_indexable(ref_2024))

    # Refresh index to ensure documents are searchable
    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    # Test various scenarios
    results = await search_service.search(
        SearchQuery(
            query_string="Test Paper",
            publication_year_range=PublicationYearRange(start=2022, end=2022),
        ),
    )
    assert len(results.hits) == 1
    assert results.hits[0].id == ref_2022.id

    results = await search_service.search(
        SearchQuery(
            query_string="Test Paper",
            publication_year_range=PublicationYearRange(start=2020, end=2023),
        ),
    )
    assert len(results.hits) == 2
    assert {hit.id for hit in results.hits} == {ref_2020.id, ref_2022.id}

    results = await search_service.search(
        SearchQuery(
            query_string="Dugong",
            publication_year_range=PublicationYearRange(start=2020, end=2023),
        ),
    )
    assert len(results.hits) == 1
    assert {hit.id for hit in results.hits} == {ref_2022.id}

    results = await search_service.search(
        SearchQuery(
            query_string="Test Paper",
            publication_year_range=PublicationYearRange(start=2021),
        ),
    )
    assert len(results.hits) == 2
    assert {hit.id for hit in results.hits} == {ref_2022.id, ref_2024.id}

    results = await search_service.search(
        SearchQuery(
            query_string="Test Paper",
            publication_year_range=PublicationYearRange(end=2021),
        ),
    )
    assert len(results.hits) == 1
    assert results.hits[0].id == ref_2020.id


@pytest.mark.parametrize(
    ("annotation_filter", "hit"),
    [
        (AnnotationFilter(scheme="taxonomy:exposure", label="Heat"), True),
        (AnnotationFilter(scheme="taxonomy:exposure", label="Pathogens"), False),
        (AnnotationFilter(scheme="inclusion:destiny", score=0.1), True),
        (AnnotationFilter(scheme="inclusion:destiny", score=0.5), False),
        (AnnotationFilter(scheme="inclusion:destiny"), False),
        (AnnotationFilter(scheme="taxonomy:outcomes"), False),
        (AnnotationFilter(scheme="taxonomy:exposure"), True),
    ],
)
async def test_search_with_query_string_taxonomy_annotation_filter(
    search_service: SearchService,
    es_reference_repository: ReferenceESRepository,
    annotation_filter: AnnotationFilter,
    *,
    hit: bool,
):
    """Test searching with annotation filters results correctly."""
    reference = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Find me by searching for Test",
                )
            ),
            EnhancementFactory.build(
                content=AnnotationEnhancementFactory.build(
                    annotations=[
                        BooleanAnnotationFactory.build(
                            scheme="taxonomy:exposure",
                            label="Heat",
                            value=True,
                        ),
                        BooleanAnnotationFactory.build(
                            scheme="taxonomy:exposure",
                            label="CO2",
                            value=True,
                        ),
                        BooleanAnnotationFactory.build(
                            scheme="taxonomy:exposure",
                            label="Pathogens",
                            value=False,
                        ),
                    ]
                )
            ),
            EnhancementFactory.build(
                content=AnnotationEnhancementFactory.build(
                    annotations=[
                        BooleanAnnotationFactory.build(
                            scheme="inclusion:destiny", value=False, score=0.8
                        )
                    ]
                )
            ),
        ],
    )

    await es_reference_repository.add(to_indexable(reference))
    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    results = await search_service.search(
        SearchQuery(
            query_string="Test",
            annotation_filters=[annotation_filter],
        ),
    )
    assert (len(results.hits) == 1) == hit


# ---- _resolve_sibling_grouping --------------------------------------------------

VOCAB_URI = "https://vocab.example.org/vocabulary/v1"

BOTANY = "https://vocab.example.org/Botany"
ZOOLOGY = "https://vocab.example.org/Zoology"
MICROBIOLOGY = "https://vocab.example.org/Microbiology"
AFRICA = "https://vocab.example.org/Africa"
ASIA = "https://vocab.example.org/Asia"
EUROPE = "https://vocab.example.org/Europe"

_TOPICS = frozenset({BOTANY, ZOOLOGY, MICROBIOLOGY})
_REGIONS = frozenset({AFRICA, ASIA, EUROPE})
SIBLINGS_FIXTURE: dict[str, frozenset[str]] = {
    **{uri: _TOPICS for uri in _TOPICS},
    **{uri: _REGIONS for uri in _REGIONS},
}


@pytest.fixture
def vocab_client_with_siblings() -> MagicMock:
    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_concept_siblings = AsyncMock(return_value=SIBLINGS_FIXTURE)
    return client


def _service(vocab_client: MagicMock) -> SearchService:
    return SearchService(
        anti_corruption_service=MagicMock(spec=ReferenceAntiCorruptionService),
        sql_uow=MagicMock(spec=AsyncSqlUnitOfWork),
        es_uow=MagicMock(spec=AsyncESUnitOfWork),
        vocab_client=vocab_client,
    )


async def test_resolve_concept_sibling_groups_happy_path(
    vocab_client_with_siblings: MagicMock,
):
    """Each filter becomes a group carrying its resolved sibling set."""
    service = _service(vocab_client_with_siblings)
    groups = await service._resolve_concept_sibling_groups(  # noqa: SLF001
        VOCAB_URI,
        [
            LinkedDataConceptFilter(concept_uris=[BOTANY, ZOOLOGY]),
            LinkedDataConceptFilter(concept_uris=[AFRICA]),
        ],
    )
    assert [list(g.selected) for g in groups] == [
        [BOTANY, ZOOLOGY],
        [AFRICA],
    ]
    assert groups[0].siblings_including_selected == _TOPICS
    assert groups[1].siblings_including_selected == _REGIONS


async def test_resolve_concept_sibling_groups_raises_sibling_grouping_error(
    vocab_client_with_siblings: MagicMock,
):
    """Rule violations bubble up as SiblingGroupingError."""
    with pytest.raises(SiblingGroupingError, match="different sibling sets"):
        await _service(vocab_client_with_siblings)._resolve_concept_sibling_groups(  # noqa: SLF001
            VOCAB_URI,
            [LinkedDataConceptFilter(concept_uris=[BOTANY, AFRICA])],
        )


async def test_aggregate_facets_naive_when_concepts_not_requested(
    vocab_client_with_siblings: MagicMock,
):
    """No concepts facet → repo called with empty mapping; vocab untouched."""
    service = _service(vocab_client_with_siblings)
    service.es_uow.references = MagicMock()  # type: ignore[union-attr]
    service.es_uow.references.aggregate_facets = AsyncMock(return_value={})  # type: ignore[union-attr]
    await service.aggregate_facets(
        SearchQuery(
            query_string="*",
            linked_data_concept_filters=[
                LinkedDataConceptFilter(concept_uris=[BOTANY])
            ],
        ),
        facets=(),
        vocabulary_uri=None,
    )
    vocab_client_with_siblings.get_concept_siblings.assert_not_called()
    _, kwargs = service.es_uow.references.aggregate_facets.call_args  # type: ignore[union-attr]
    assert kwargs["sibling_groups_by_facet"] == {}


async def test_aggregate_facets_raises_when_vocab_missing_but_required(
    vocab_client_with_siblings: MagicMock,
):
    """Concepts facet + concept filter + no vocab → SiblingGroupingError."""
    service = _service(vocab_client_with_siblings)
    with pytest.raises(SiblingGroupingError, match="`vocabulary=` is required"):
        await service.aggregate_facets(
            SearchQuery(
                query_string="*",
                linked_data_concept_filters=[
                    LinkedDataConceptFilter(concept_uris=[BOTANY])
                ],
            ),
            facets=(FacetType.CONCEPTS,),
            vocabulary_uri=None,
        )


def test_validate_groups_against_max_buckets():
    """Groups within the limit pass; over the limit raises SiblingGroupingError."""
    groups = (
        SiblingGroup(
            selected=(BOTANY, ZOOLOGY),
            siblings_including_selected=frozenset({BOTANY, ZOOLOGY, MICROBIOLOGY}),
        ),
    )
    SearchService._validate_groups_against_max_buckets(groups, max_buckets=3)  # noqa: SLF001
    with pytest.raises(SiblingGroupingError, match="exceeding max_buckets"):
        SearchService._validate_groups_against_max_buckets(groups, max_buckets=2)  # noqa: SLF001
