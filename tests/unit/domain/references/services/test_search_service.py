"""Integration tests for search service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from elasticsearch import AsyncElasticsearch
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SiblingGroupingError
from app.domain.references.models.models import (
    AnnotationFilter,
    LinkedDataConceptFilter,
    PublicationYearRange,
    SearchQuery,
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

# Biology siblings (hierarchical); Africa/Asia/Europe siblings (flat scheme);
# Loose has no sibling map entry, simulating an unknown URI.
SIBLINGS_FIXTURE: dict[str, frozenset[str]] = {
    "https://vocab.example.org/Botany": frozenset(
        {
            "https://vocab.example.org/Botany",
            "https://vocab.example.org/Zoology",
            "https://vocab.example.org/Microbiology",
        }
    ),
    "https://vocab.example.org/Zoology": frozenset(
        {
            "https://vocab.example.org/Botany",
            "https://vocab.example.org/Zoology",
            "https://vocab.example.org/Microbiology",
        }
    ),
    "https://vocab.example.org/Microbiology": frozenset(
        {
            "https://vocab.example.org/Botany",
            "https://vocab.example.org/Zoology",
            "https://vocab.example.org/Microbiology",
        }
    ),
    "https://vocab.example.org/Africa": frozenset(
        {
            "https://vocab.example.org/Africa",
            "https://vocab.example.org/Asia",
            "https://vocab.example.org/Europe",
        }
    ),
    "https://vocab.example.org/Asia": frozenset(
        {
            "https://vocab.example.org/Africa",
            "https://vocab.example.org/Asia",
            "https://vocab.example.org/Europe",
        }
    ),
    "https://vocab.example.org/Europe": frozenset(
        {
            "https://vocab.example.org/Africa",
            "https://vocab.example.org/Asia",
            "https://vocab.example.org/Europe",
        }
    ),
}

BOTANY = "https://vocab.example.org/Botany"
ZOOLOGY = "https://vocab.example.org/Zoology"
MICROBIOLOGY = "https://vocab.example.org/Microbiology"
AFRICA = "https://vocab.example.org/Africa"
UNKNOWN = "https://vocab.example.org/Unknown"


@pytest.fixture
def vocab_client_with_siblings() -> MagicMock:
    """Mock vocab client returning the SIBLINGS_FIXTURE map."""
    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_concept_siblings = AsyncMock(return_value=SIBLINGS_FIXTURE)
    return client


def _service(vocab_client: MagicMock) -> SearchService:
    """Build a SearchService without UoW dependencies for pure-resolver tests."""
    anti_corruption_service = MagicMock(spec=ReferenceAntiCorruptionService)
    return SearchService(
        anti_corruption_service=anti_corruption_service,
        sql_uow=MagicMock(spec=AsyncSqlUnitOfWork),
        es_uow=MagicMock(spec=AsyncESUnitOfWork),
        vocab_client=vocab_client,
    )


async def test_resolve_sibling_grouping_happy_path(
    vocab_client_with_siblings: MagicMock,
):
    """Two well-formed filters produce two groups with their sibling sets."""
    service = _service(vocab_client_with_siblings)
    grouping = await service._resolve_sibling_grouping(  # noqa: SLF001
        VOCAB_URI,
        [
            LinkedDataConceptFilter(concept_uris=[BOTANY, ZOOLOGY]),
            LinkedDataConceptFilter(concept_uris=[AFRICA]),
        ],
    )
    assert len(grouping.groups) == 2
    assert grouping.groups[0].source_filter.concept_uris == [BOTANY, ZOOLOGY]
    assert grouping.groups[0].siblings_including_selected == frozenset(
        {BOTANY, ZOOLOGY, MICROBIOLOGY}
    )
    assert grouping.groups[1].source_filter.concept_uris == [AFRICA]
    assert grouping.groups[1].siblings_including_selected == SIBLINGS_FIXTURE[AFRICA]
    assert grouping.all_grouped_uris == frozenset(
        {BOTANY, ZOOLOGY, MICROBIOLOGY, AFRICA, *SIBLINGS_FIXTURE[AFRICA]}
    )


async def test_resolve_sibling_grouping_unknown_uri_raises(
    vocab_client_with_siblings: MagicMock,
):
    """Rule (c): every URI must resolve in the supplied vocabulary."""
    service = _service(vocab_client_with_siblings)
    with pytest.raises(SiblingGroupingError, match=UNKNOWN):
        await service._resolve_sibling_grouping(  # noqa: SLF001
            VOCAB_URI,
            [LinkedDataConceptFilter(concept_uris=[BOTANY, UNKNOWN])],
        )


async def test_resolve_sibling_grouping_mixed_sibling_sets_in_one_filter_raises(
    vocab_client_with_siblings: MagicMock,
):
    """Rule (a): URIs in one filter must share a sibling set."""
    service = _service(vocab_client_with_siblings)
    with pytest.raises(SiblingGroupingError, match="different sibling sets"):
        await service._resolve_sibling_grouping(  # noqa: SLF001
            VOCAB_URI,
            [LinkedDataConceptFilter(concept_uris=[BOTANY, AFRICA])],
        )


async def test_resolve_sibling_grouping_siblings_split_across_filters_raises(
    vocab_client_with_siblings: MagicMock,
):
    """Rule (b): siblings can't be split across separate filters."""
    service = _service(vocab_client_with_siblings)
    with pytest.raises(SiblingGroupingError, match="share a sibling set"):
        await service._resolve_sibling_grouping(  # noqa: SLF001
            VOCAB_URI,
            [
                LinkedDataConceptFilter(concept_uris=[BOTANY]),
                LinkedDataConceptFilter(concept_uris=[ZOOLOGY]),
            ],
        )


async def test_aggregate_facets_naive_when_no_vocab(
    vocab_client_with_siblings: MagicMock,
):
    """When vocabulary_uri is None, the naive path is taken: vocab client untouched."""
    service = _service(vocab_client_with_siblings)
    service.es_uow.references = MagicMock()  # type: ignore[union-attr]
    service.es_uow.references.aggregate_facets = AsyncMock(  # type: ignore[union-attr]
        return_value={},
    )
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
    # Repo is still called, with an empty grouping.
    args, kwargs = service.es_uow.references.aggregate_facets.call_args  # type: ignore[union-attr]
    grouping = args[2]
    assert grouping.is_empty
