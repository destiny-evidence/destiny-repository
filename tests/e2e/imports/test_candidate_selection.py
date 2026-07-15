"""End-to-end tests for the candidate-selection API."""

from collections.abc import Callable
from contextlib import _AsyncGeneratorContextManager

import httpx
import pytest
from destiny_sdk.enhancements import Authorship
from destiny_sdk.identifiers import DOIIdentifier
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import Reference, Visibility
from app.domain.references.models.sql import ReferenceDuplicateDecision
from tests.e2e.utils import import_references, refresh_reference_index
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    ReferenceFactory,
)

CANDIDATES_URL = "references/deduplication/candidates/"


@pytest.fixture
def doi() -> DOIIdentifier:
    """Build a DOI reused across the reference and the request payload."""
    return DOIIdentifierFactory.build()


@pytest.fixture
def canonical_reference(doi: DOIIdentifier) -> Reference:
    """Build a searchable reference with a bibliographic enhancement and a DOI."""
    return ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="A Distinctive Candidate Selection Study",
                    authorship=[
                        Authorship(display_name="Ada Lovelace", position="first"),
                        Authorship(display_name="Alan Turing", position="last"),
                    ],
                    publication_year=2024,
                )
            )
        ],
        identifiers=[LinkedExternalIdentifierFactory.build(identifier=doi)],
        visibility=Visibility.PUBLIC,
    )


async def _count_duplicate_decisions(pg_session: AsyncSession) -> int:
    result = await pg_session.execute(
        select(func.count()).select_from(ReferenceDuplicateDecision)
    )
    return result.scalar_one()


async def test_candidates_inline_unions_es_and_identifier_without_persisting(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    doi: DOIIdentifier,
):
    """Inline input returns the seeded canonical via both ES and identifier routes."""
    reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()
    await refresh_reference_index(es_client)

    decisions_before = await _count_duplicate_decisions(pg_session)

    response = await destiny_client_v1.post(
        CANDIDATES_URL,
        json={
            "input": {
                "title": "A Distinctive Candidate Selection Study",
                "authors": ["Ada Lovelace", "Alan Turing"],
                "publication_year": 2024,
                "identifiers": [
                    {"identifier_type": "doi", "identifier": str(doi.identifier)}
                ],
            },
            "k": 50,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retrieval_policy"] == "current_fuzzy_v1"
    assert body["index_version"].startswith("reference_v")
    assert body["k_requested"] == 50
    assert body["input_searchability"]["searchable"] is True

    candidate = next(
        c for c in body["candidates"] if c["reference_id"] == str(reference_id)
    )
    route_types = {route["type"] for route in candidate["routes"]}
    assert route_types == {"elasticsearch", "identifier"}
    identifier_route = next(r for r in candidate["routes"] if r["type"] == "identifier")
    assert identifier_route["matched_identifiers"][0]["identifier"] == str(
        doi.identifier
    )
    assert candidate["reference"]["title"] == "A Distinctive Candidate Selection Study"
    assert candidate["reference"]["publication_year"] == 2024

    # Isolated per test: exactly the one imported reference, found by both routes
    # and collapsed to a single candidate by the union.
    assert body["diagnostics"]["es_returned"] == 1
    assert body["diagnostics"]["identifier_returned"] == 1
    assert body["diagnostics"]["candidate_count"] == 1

    # Read-only: the request must not create or change any duplicate-decision state.
    assert await _count_duplicate_decisions(pg_session) == decisions_before


async def test_candidates_by_reference_id_is_searchable_and_read_only(
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
):
    """reference_id input projects the stored reference and writes no state."""
    reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()
    await refresh_reference_index(es_client)

    decisions_before = await _count_duplicate_decisions(pg_session)

    response = await destiny_client_v1.post(
        CANDIDATES_URL,
        json={"input": {"reference_id": str(reference_id)}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["input_searchability"]["searchable"] is True
    assert body["k_requested"] == 100  # configured default
    # The input reference excludes itself from its own candidates.
    assert all(c["reference_id"] != str(reference_id) for c in body["candidates"])
    assert await _count_duplicate_decisions(pg_session) == decisions_before


async def test_candidates_identifier_only_input_matches_despite_unsearchable(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    doi: DOIIdentifier,
):
    """An identifier-only payload (no title/authors/year) still matches by DOI."""
    reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()
    await refresh_reference_index(es_client)

    response = await destiny_client_v1.post(
        CANDIDATES_URL,
        json={
            "input": {
                "identifiers": [
                    {"identifier_type": "doi", "identifier": str(doi.identifier)}
                ]
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["input_searchability"]["searchable"] is False
    candidate = next(
        c for c in body["candidates"] if c["reference_id"] == str(reference_id)
    )
    assert [route["type"] for route in candidate["routes"]] == ["identifier"]


async def test_candidates_unsearchable_returns_empty_200(
    destiny_client_v1: httpx.AsyncClient,
):
    """A record without enough bibliographic signal returns empty candidates."""
    response = await destiny_client_v1.post(
        CANDIDATES_URL,
        json={"input": {"title": "Lonely title, no authors or year"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["input_searchability"]["searchable"] is False
    assert body["candidates"] == []


async def test_candidates_rejects_both_and_neither_inputs(
    destiny_client_v1: httpx.AsyncClient,
):
    """The input must be exactly one of reference_id or inline fields."""
    neither = await destiny_client_v1.post(CANDIDATES_URL, json={"input": {}})
    assert neither.status_code == 422

    both = await destiny_client_v1.post(
        CANDIDATES_URL,
        json={
            "input": {
                "reference_id": str(ReferenceFactory.build().id),
                "title": "A title",
            }
        },
    )
    assert both.status_code == 422
