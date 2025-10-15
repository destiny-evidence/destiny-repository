"""End-to-end tests for import deduplication."""

from collections.abc import Callable
from contextlib import _AsyncGeneratorContextManager

import httpx
import pytest
from destiny_sdk.enhancements import Authorship, BibliographicMetadataEnhancement
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    Reference,
)
from tests.e2e.utils import import_references, poll_duplicate_process
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    ReferenceFactory,
)


@pytest.fixture
def canonical_bibliographic_enhancement() -> BibliographicMetadataEnhancement:
    """Get a pre-defined bibliographic enhancement."""
    return BibliographicMetadataEnhancementFactory.build(
        title="A Study on the Effects of Testing",
        authorship=[
            Authorship(display_name="Jane Doe", position="first"),
            Authorship(display_name="John Smith", position="last"),
        ],
        publication_year=2025,
    )


@pytest.fixture
def canonical_reference(canonical_bibliographic_enhancement: Enhancement) -> Reference:
    """Get a pre-defined canonical reference."""
    return ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(content=canonical_bibliographic_enhancement),
            # Some other enhancement
            EnhancementFactory.build(),
        ],
        identifiers=[
            # Make sure we have at least one non-other identifier
            LinkedExternalIdentifierFactory.build(
                identifier=DOIIdentifierFactory.build()
            ),
            LinkedExternalIdentifierFactory.build(),
        ],
    )


async def test_import_duplicates(
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
):
    """Test importing a duplicate reference."""
    canonical_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()

    # First, an exact duplicate. Check that the decision is correct and that the
    # reference is not imported.
    exact_duplicate_reference = canonical_reference.model_copy(deep=True)
    # Make it a subsetting reference
    assert exact_duplicate_reference.enhancements
    exact_duplicate_reference.enhancements.pop()
    exact_duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            [exact_duplicate_reference],
            get_import_file_signed_url,
        )
    ).pop()
    duplicate_decision = await poll_duplicate_process(
        pg_session, exact_duplicate_reference_id
    )
    assert (
        duplicate_decision["duplicate_determination"]
        == DuplicateDetermination.EXACT_DUPLICATE
    )
    pg_result = await pg_session.execute(
        text("SELECT COUNT(*) FROM reference WHERE id=:id;"),
        {"id": exact_duplicate_reference_id},
    )
    assert pg_result.scalar_one() == 0

    # Now, a near duplicate. Modify it a small amount and check the decision is correct
    # and that the reference is imported.
    duplicate = canonical_reference.model_copy(deep=True)
    assert duplicate.enhancements
    assert duplicate.enhancements[0]
    assert isinstance(
        duplicate.enhancements[0].content, BibliographicMetadataEnhancement
    )
    duplicate.enhancements[0].content.title = "A Study on the Effects of Testing!"
    assert duplicate.enhancements[0].content.authorship
    duplicate.enhancements[0].content.authorship[0] = Authorship(
        display_name="Jayne Doe", position="first"
    )
    duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            [duplicate],
            get_import_file_signed_url,
        )
    ).pop()
    duplicate_decision = await poll_duplicate_process(
        pg_session, duplicate_reference_id
    )
    assert (
        duplicate_decision["duplicate_determination"]
        == DuplicateDetermination.DUPLICATE
    )
    assert duplicate_decision["canonical_reference_id"] == canonical_reference_id

    # Check that the Elasticsearch index contains only the canonical, with the near
    # duplicate's data merged in.
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)
    es_result = await es_client.search(
        index=ReferenceDocument.Index.name,
        query={
            "terms": {
                "_id": [
                    str(canonical_reference_id),
                    str(duplicate_reference_id),
                ]
            }
        },
    )
    assert es_result["hits"]["total"]["value"] == 1
    assert es_result["hits"]["hits"][0]["_id"] == str(canonical_reference_id)
    es_source = es_result["hits"]["hits"][0]["_source"]
    assert es_source["duplicate_determination"] == "canonical"

    authors, titles = set(), set()
    for enhancement in es_source["enhancements"]:
        if enhancement["content"]["enhancement_type"] == "bibliographic":
            titles.add(enhancement["content"]["title"])
            for author in enhancement["content"]["authorship"]:
                authors.add(author["display_name"])
    assert titles >= {
        "A Study on the Effects of Testing",
        "A Study on the Effects of Testing!",
    }
    assert authors >= {"Jayne Doe", "Jane Doe", "John Smith"}
