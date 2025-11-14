"""Integration tests for search service."""

import pytest
from elasticsearch import AsyncElasticsearch
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import AnnotationFilter, PublicationYearRange
from app.domain.references.repository import ReferenceESRepository
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.search_service import SearchService
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
    anti_corruption_service = ReferenceAntiCorruptionService(blob_repo)
    es_uow = AsyncESUnitOfWork(es_client)
    es_uow._is_active = True  # noqa: SLF001
    es_uow.references = es_reference_repository
    sql_uow = AsyncSqlUnitOfWork(session)

    return SearchService(
        anti_corruption_service=anti_corruption_service,
        sql_uow=sql_uow,
        es_uow=es_uow,
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
    await es_reference_repository.add(ref_2020)
    await es_reference_repository.add(ref_2022)
    await es_reference_repository.add(ref_2024)

    # Refresh index to ensure documents are searchable
    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    # Test various scenarios
    results = await search_service.search_with_query_string(
        query_string="Test Paper",
        publication_year_range=PublicationYearRange(start=2022, end=2022),
    )
    assert len(results.hits) == 1
    assert results.hits[0].id == ref_2022.id

    results = await search_service.search_with_query_string(
        query_string="Test Paper",
        publication_year_range=PublicationYearRange(start=2020, end=2023),
    )
    assert len(results.hits) == 2
    assert {hit.id for hit in results.hits} == {ref_2020.id, ref_2022.id}

    results = await search_service.search_with_query_string(
        query_string="Dugong",
        publication_year_range=PublicationYearRange(start=2020, end=2023),
    )
    assert len(results.hits) == 1
    assert {hit.id for hit in results.hits} == {ref_2022.id}

    results = await search_service.search_with_query_string(
        query_string="Test Paper",
        publication_year_range=PublicationYearRange(start=2021),
    )
    assert len(results.hits) == 2
    assert {hit.id for hit in results.hits} == {ref_2022.id, ref_2024.id}

    results = await search_service.search_with_query_string(
        query_string="Test Paper",
        publication_year_range=PublicationYearRange(end=2021),
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

    await es_reference_repository.add(reference)
    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    results = await search_service.search_with_query_string(
        query_string="Test",
        annotations=[annotation_filter],
    )
    assert (len(results.hits) == 1) == hit
