"""Unit tests for the candidate-selection API orchestration and models."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from destiny_sdk.enhancements import Authorship
from pydantic import ValidationError

from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import (
    CandidateElasticsearchRoute,
    CandidateIdentifier,
    CandidateSelectionInput,
    CandidateSelectionRequest,
    DuplicateDetermination,
    ExternalIdentifierType,
    Reference,
    ReferenceDuplicateDecision,
    RetrievalPolicyName,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.es.persistence import (
    CandidateCanonicalSearchResult,
    ESScoreResult,
    ESSearchTotal,
)
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    ReferenceFactory,
)


def _searchable_reference(**update: object) -> Reference:
    """Build a reference with a searchable bibliographic enhancement."""
    reference = ReferenceFactory.build(visibility="public")
    return reference.model_copy(
        update={
            "enhancements": [
                EnhancementFactory.build(
                    reference_id=reference.id,
                    content=BibliographicMetadataEnhancementFactory.build(
                        authorship=[
                            Authorship(display_name="John Doe", position="first")
                        ],
                        publication_year=2025,
                        title="Maybe a duplicate reference, maybe not",
                    ),
                )
            ],
            **update,
        }
    )


def _es_result(
    *hits: ESScoreResult, total: int | None = None
) -> CandidateCanonicalSearchResult:
    return CandidateCanonicalSearchResult(
        hits=list(hits),
        total=ESSearchTotal(
            value=total if total is not None else len(hits), relation="eq"
        ),
        took_ms=7,
    )


@pytest.fixture
def anti_corruption_service():
    return MagicMock(spec=ReferenceAntiCorruptionService)


@pytest.fixture
def build_service(fake_uow, anti_corruption_service):
    """Build a ReferenceService with mocked ES/SQL reference repositories."""

    def _build(
        *,
        es_result: CandidateCanonicalSearchResult | None = None,
        found_references: list[Reference] | None = None,
        hydrated: list[Reference] | None = None,
        reference: Reference | None = None,
        index_name: str | None = "reference_v3",
    ) -> tuple[ReferenceService, MagicMock, MagicMock, MagicMock]:
        es_refs = MagicMock()
        es_refs.get_current_index_name = AsyncMock(return_value=index_name)
        es_refs.search_for_candidate_canonicals = AsyncMock(
            return_value=es_result if es_result is not None else _es_result()
        )

        sql_refs = MagicMock()
        sql_refs.get_by_pk = AsyncMock(return_value=reference)
        sql_refs.find_with_identifiers = AsyncMock(return_value=found_references or [])
        sql_refs.get_hydrated = AsyncMock(return_value=hydrated or [])

        decisions = MagicMock()
        decisions.add = AsyncMock()
        decisions.add_bulk = AsyncMock()
        decisions.update_by_pk = AsyncMock()
        decisions.merge = AsyncMock()

        service = ReferenceService(
            anti_corruption_service,
            fake_uow(references=sql_refs, reference_duplicate_decisions=decisions),
            fake_uow(references=es_refs),
        )
        return service, es_refs, sql_refs, decisions

    return _build


class TestCandidateSelectionInputValidation:
    def test_rejects_neither(self):
        with pytest.raises(ValidationError):
            CandidateSelectionInput()

    def test_rejects_both(self):
        with pytest.raises(ValidationError):
            CandidateSelectionInput(reference_id=uuid7(), title="A title")

    def test_accepts_reference_id(self):
        input_ = CandidateSelectionInput(reference_id=uuid7())
        assert input_.reference_id is not None

    def test_accepts_inline(self):
        input_ = CandidateSelectionInput(
            title="A title", authors=["Jane"], publication_year=2020
        )
        assert input_.title == "A title"

    def test_k_bounds_enforced(self):
        with pytest.raises(ValidationError):
            CandidateSelectionRequest(
                input=CandidateSelectionInput(reference_id=uuid7()), k=0
            )
        with pytest.raises(ValidationError):
            CandidateSelectionRequest(
                input=CandidateSelectionInput(reference_id=uuid7()), k=1001
            )

    def test_rejects_removed_include_identifier_matches(self):
        with pytest.raises(ValidationError):
            CandidateSelectionRequest.model_validate(
                {
                    "input": {
                        "title": "t",
                        "authors": ["a"],
                        "publication_year": 2020,
                    },
                    "include_identifier_matches": False,
                }
            )

    def test_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            CandidateSelectionRequest.model_validate(
                {
                    "input": {
                        "title": "t",
                        "authors": ["a"],
                        "publication_year": 2020,
                    },
                    "not_a_real_field": 1,
                }
            )


def test_unknown_retrieval_policy_rejected_by_request_model():
    """An unknown policy is rejected when the request is built (a 422 at the API)."""
    with pytest.raises(ValidationError):
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="t", authors=["a"], publication_year=2020
            ),
            retrieval_policy="no_such_policy",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_no_year_filter_v1_passes_strategy_and_stamps_policy(build_service):
    hit = uuid7()
    service, es_refs, _, _ = build_service(
        es_result=_es_result(ESScoreResult(id=hit, score=5.0))
    )

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="t", authors=["a"], publication_year=2020
            ),
            retrieval_policy=RetrievalPolicyName.NO_YEAR_FILTER_V1,
            hydrate=False,
        )
    )

    query = es_refs.search_for_candidate_canonicals.call_args.args[0]
    assert query.publication_year_range is None
    assert result.retrieval_policy == RetrievalPolicyName.NO_YEAR_FILTER_V1
    es_route_policies = [
        route.policy
        for candidate in result.candidates
        for route in candidate.routes
        if isinstance(route, CandidateElasticsearchRoute)
    ]
    assert es_route_policies
    assert all(p == "no_year_filter_v1" for p in es_route_policies)


@pytest.mark.asyncio
async def test_year_optional_policy_searches_missing_year_input(build_service):
    service, es_refs, _, _ = build_service(
        es_result=_es_result(ESScoreResult(id=uuid7(), score=4.0))
    )

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(title="t", authors=["a"]),  # no year
            retrieval_policy=RetrievalPolicyName.NO_YEAR_FILTER_YEAR_OPTIONAL_V1,
            hydrate=False,
        )
    )

    assert result.input_searchability.searchable is True
    es_refs.search_for_candidate_canonicals.assert_awaited_once()
    query = es_refs.search_for_candidate_canonicals.call_args.args[0]
    assert query.publication_year_range is None


@pytest.mark.asyncio
async def test_missing_year_input_unsearchable_under_control(build_service):
    service, es_refs, _, _ = build_service()

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(title="t", authors=["a"]),  # no year
            retrieval_policy=RetrievalPolicyName.CURRENT_FUZZY_V1,
        )
    )

    assert result.input_searchability.searchable is False
    es_refs.search_for_candidate_canonicals.assert_not_awaited()


@pytest.mark.asyncio
async def test_inline_input_returns_ranked_es_candidates(build_service):
    id1, id2 = uuid7(), uuid7()
    es_result = _es_result(
        ESScoreResult(id=id1, score=9.0), ESScoreResult(id=id2, score=8.0)
    )
    service, es_refs, _, _ = build_service(es_result=es_result)

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="A study", authors=["Jane Doe"], publication_year=2025
            ),
            hydrate=False,
        )
    )

    assert result.retrieval_policy == RetrievalPolicyName.CURRENT_FUZZY_V1
    assert result.index_version == "reference_v3"
    assert result.input_searchability.searchable is True
    assert [c.reference_id for c in result.candidates] == [id1, id2]
    assert [c.rank for c in result.candidates] == [1, 2]
    first_route = result.candidates[0].routes[0]
    assert first_route.type == "elasticsearch"
    assert first_route.score == 9.0
    assert result.candidates[0].reference is None
    assert result.diagnostics.es_returned == 2
    assert result.diagnostics.candidate_count == 2
    assert result.diagnostics.identifier_returned == 0
    assert result.diagnostics.lowest_es_score == 8.0


@pytest.mark.asyncio
async def test_reference_id_input_self_excludes_and_defaults_k(build_service):
    reference = _searchable_reference()
    hit = uuid7()
    service, es_refs, sql_refs, _ = build_service(
        reference=reference,
        es_result=_es_result(ESScoreResult(id=hit, score=3.0)),
    )

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(reference_id=reference.id),
            hydrate=False,
        )
    )

    sql_refs.get_by_pk.assert_awaited_once()
    query = es_refs.search_for_candidate_canonicals.call_args.args[0]
    kwargs = es_refs.search_for_candidate_canonicals.call_args.kwargs
    assert query.excluded_reference_id == reference.id
    assert kwargs["k"] == 100  # configured default
    assert result.k_requested == 100
    assert [c.reference_id for c in result.candidates] == [hit]


@pytest.mark.asyncio
async def test_k_override_passed_to_es(build_service):
    service, es_refs, _, _ = build_service()

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="A study", authors=["Jane Doe"], publication_year=2025
            ),
            k=25,
            hydrate=False,
        )
    )

    _, kwargs = es_refs.search_for_candidate_canonicals.call_args
    assert kwargs["k"] == 25
    assert result.k_requested == 25


@pytest.mark.asyncio
async def test_identifier_only_match_ranks_ahead_of_es(build_service):
    doi = DOIIdentifierFactory.build()
    identifier_ref = ReferenceFactory.build(visibility="public")
    identifier_ref = identifier_ref.model_copy(
        update={
            "identifiers": [
                LinkedExternalIdentifierFactory.build(
                    identifier=doi, reference_id=identifier_ref.id
                )
            ],
            "duplicate_decision": None,  # canonical-like
        }
    )
    es_id = uuid7()
    service, _, sql_refs, _ = build_service(
        es_result=_es_result(ESScoreResult(id=es_id, score=5.0)),
        found_references=[identifier_ref],
    )

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="A study",
                authors=["Jane Doe"],
                publication_year=2025,
                identifiers=[
                    CandidateIdentifier(
                        identifier_type=ExternalIdentifierType.DOI,
                        identifier=str(doi.identifier),
                    )
                ],
            ),
            hydrate=False,
        )
    )

    # Identifier-only match first, then the ES-scored candidate.
    assert [c.reference_id for c in result.candidates] == [identifier_ref.id, es_id]
    assert result.candidates[0].rank == 1
    id_route = result.candidates[0].routes[0]
    assert id_route.type == "identifier"
    assert id_route.matched_identifiers[0].identifier == str(doi.identifier)
    assert result.candidates[1].routes[0].type == "elasticsearch"
    assert result.diagnostics.identifier_returned == 1
    assert result.diagnostics.candidate_count == 2


@pytest.mark.asyncio
async def test_identifier_match_on_duplicate_resolves_to_canonical(build_service):
    doi = DOIIdentifierFactory.build()
    canonical_id = uuid7()
    duplicate = ReferenceFactory.build(visibility="public")
    duplicate = duplicate.model_copy(
        update={
            "identifiers": [
                LinkedExternalIdentifierFactory.build(
                    identifier=doi, reference_id=duplicate.id
                )
            ],
            "duplicate_decision": ReferenceDuplicateDecision(
                reference_id=duplicate.id,
                active_decision=True,
                duplicate_determination=DuplicateDetermination.DUPLICATE,
                canonical_reference_id=canonical_id,
            ),
        }
    )
    service, _, _, _ = build_service(found_references=[duplicate])

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="A study",
                authors=["Jane Doe"],
                publication_year=2025,
                identifiers=[
                    CandidateIdentifier(
                        identifier_type=ExternalIdentifierType.DOI,
                        identifier=str(doi.identifier),
                    )
                ],
            ),
            hydrate=False,
        )
    )

    assert [c.reference_id for c in result.candidates] == [canonical_id]


@pytest.mark.asyncio
async def test_hydrate_includes_reference_projection(build_service):
    hit = uuid7()
    hydrated = _searchable_reference().model_copy(update={"id": hit})
    service, _, _, _ = build_service(
        es_result=_es_result(ESScoreResult(id=hit, score=4.0)),
        hydrated=[hydrated],
    )

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="A study", authors=["Jane Doe"], publication_year=2025
            ),
            hydrate=True,
        )
    )

    candidate = result.candidates[0]
    assert candidate.reference is not None
    assert candidate.reference.title == "Maybe a duplicate reference, maybe not"
    assert candidate.reference.publication_year == 2025


@pytest.mark.asyncio
async def test_identifier_only_input_matches_when_es_unsearchable(build_service):
    """An identifier-only input still surfaces exact matches despite the gate."""
    doi = DOIIdentifierFactory.build()
    identifier_ref = ReferenceFactory.build(visibility="public")
    identifier_ref = identifier_ref.model_copy(
        update={
            "identifiers": [
                LinkedExternalIdentifierFactory.build(
                    identifier=doi, reference_id=identifier_ref.id
                )
            ],
            "duplicate_decision": None,
        }
    )
    service, es_refs, _, _ = build_service(found_references=[identifier_ref])

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                identifiers=[
                    CandidateIdentifier(
                        identifier_type=ExternalIdentifierType.DOI,
                        identifier=str(doi.identifier),
                    )
                ]
            ),
            hydrate=False,
        )
    )

    # The ES gate is not met, but the identifier route still returns the match.
    assert result.input_searchability.searchable is False
    es_refs.search_for_candidate_canonicals.assert_not_awaited()
    assert [c.reference_id for c in result.candidates] == [identifier_ref.id]
    assert result.candidates[0].routes[0].type == "identifier"
    assert result.diagnostics.identifier_returned == 1
    assert result.diagnostics.es_total_hits is None


async def test_invalid_identifier_raises(build_service):
    """A malformed identifier value fails normalisation and raises (422 in the API)."""
    service, _, _, _ = build_service()
    with pytest.raises(DeduplicationValueError):
        await service.get_deduplication_candidates(
            CandidateSelectionRequest(
                input=CandidateSelectionInput(
                    identifiers=[
                        CandidateIdentifier(
                            identifier_type=ExternalIdentifierType.DOI,
                            identifier="not-a-doi",
                        )
                    ]
                ),
                hydrate=False,
            )
        )


async def test_unsearchable_input_returns_empty_200(build_service):
    service, es_refs, _, _ = build_service()

    result = await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            # No authors -> not searchable.
            input=CandidateSelectionInput(title="A study", publication_year=2025),
        )
    )

    assert result.input_searchability.searchable is False
    assert "authors" in result.input_searchability.reason
    assert result.candidates == []
    es_refs.search_for_candidate_canonicals.assert_not_awaited()


@pytest.mark.asyncio
async def test_writes_no_duplicate_decision_state(build_service):
    service, _, _, decisions = build_service(
        es_result=_es_result(ESScoreResult(id=uuid7(), score=1.0))
    )

    await service.get_deduplication_candidates(
        CandidateSelectionRequest(
            input=CandidateSelectionInput(
                title="A study", authors=["Jane Doe"], publication_year=2025
            ),
            hydrate=False,
        )
    )

    decisions.add.assert_not_awaited()
    decisions.add_bulk.assert_not_awaited()
    decisions.update_by_pk.assert_not_awaited()
    decisions.merge.assert_not_awaited()
