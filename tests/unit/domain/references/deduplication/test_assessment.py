from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid7

import destiny_sdk
import pytest
from destiny_sdk.visibility import Visibility
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.exceptions import (
    DeduplicationError,
    DeduplicationValueError,
    ESError,
    NotFoundError,
)
from app.domain.references.models.models import (
    Candidate,
    CandidateIdentifier,
    CandidateIdentifierRoute,
    CandidateSelectionDiagnostics,
    CandidateSelectionInput,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessmentOutcome,
    DeduplicationFieldComparison,
    DeduplicationFieldStatus,
    DeduplicationPairResult,
    EnhancementType,
    ExternalIdentifierType,
    InputSearchability,
    Reference,
    RetrievalPolicyName,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_assessment_service import (
    DeduplicationAssessmentService,
    ReferenceReader,
)
from app.domain.references.services.deduplication_service import DeduplicationService
from app.persistence.es.persistence import (
    CandidateCanonicalSearchResult,
    ESSearchTotal,
)
from tests.factories import (
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    BooleanAnnotationFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    ReferenceFactory,
)


@pytest.fixture
def anti_corruption_service() -> ReferenceAntiCorruptionService:
    return ReferenceAntiCorruptionService(sign_url=AsyncMock())


def _reference(*, community_bound: bool = False) -> Reference:
    enhancements = [
        EnhancementFactory.build(
            content=BibliographicMetadataEnhancementFactory.build(
                title="A complete reference",
            )
        )
    ]
    if community_bound:
        enhancements.append(
            EnhancementFactory.build(
                content=AnnotationEnhancementFactory.build(
                    annotations=[
                        BooleanAnnotationFactory.build(
                            scheme="community", label="esea", value=True
                        )
                    ]
                )
            )
        )
    reference = ReferenceFactory.build(
        enhancements=enhancements,
        identifiers=[
            LinkedExternalIdentifierFactory.build(
                identifier=OpenAlexIdentifierFactory.build()
            )
        ],
        visibility="public",
    )
    for enhancement in reference.enhancements or []:
        enhancement.reference_id = reference.id
    for identifier in reference.identifiers or []:
        identifier.reference_id = reference.id
    return reference


def _supplied_reference() -> destiny_sdk.references.Reference:
    """Build the frozen SDK shape supplied by an evaluation runner."""
    reference_id = uuid7()
    return destiny_sdk.references.Reference(
        id=reference_id,
        visibility=Visibility.PUBLIC,
        identifiers=[OpenAlexIdentifierFactory.build()],
        enhancements=[
            destiny_sdk.enhancements.Enhancement(
                reference_id=reference_id,
                source="evaluation-benchmark",
                visibility=Visibility.PUBLIC,
                content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                    title="A supplied reference",
                ),
            )
        ],
    )


def _supplied_input(
    reference: destiny_sdk.references.Reference,
    *,
    excluded_reference_id: UUID | None = None,
) -> CandidateSelectionInput:
    """Build the query payload a caller supplies alongside its own reference."""
    return CandidateSelectionInput(
        title="A complete reference",
        authors=["Jane Doe"],
        publication_year=2025,
        identifiers=[
            CandidateIdentifier.from_specific(identifier)
            for identifier in (reference.identifiers or [])
        ],
        excluded_reference_id=excluded_reference_id,
    )


def _selection(
    *candidates: Candidate, searchable: bool = True
) -> CandidateSelectionResult:
    return CandidateSelectionResult(
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        index_version="reference_v3" if searchable else None,
        k_requested=10,
        input_searchability=InputSearchability(
            searchable=searchable,
            reason="ok" if searchable else "missing title and authors",
        ),
        diagnostics=CandidateSelectionDiagnostics(
            candidate_count=len(candidates),
            identifier_returned=sum(
                any(route.type == "identifier" for route in candidate.routes)
                for candidate in candidates
            ),
        ),
        candidates=list(candidates),
    )


class FakePairScorer:
    def __init__(
        self,
        probabilities: dict[UUID, float | None],
        *,
        threshold: float = 0.85,
    ) -> None:
        self.metadata = DeduperMetadata(
            package_version="fake-1",
            configuration_hash="test-config",
            threshold=threshold,
            effective_configuration={"weights": "test"},
        )
        self.probabilities = probabilities
        self.calls: list[
            tuple[
                destiny_sdk.references.Reference,
                destiny_sdk.references.Reference,
            ]
        ] = []

    async def score_pair(
        self,
        incoming: destiny_sdk.references.Reference,
        candidate: destiny_sdk.references.Reference,
    ) -> DeduplicationPairResult:
        self.calls.append((incoming, candidate))
        probability = self.probabilities[candidate.id]
        if probability is None:
            return DeduplicationPairResult(
                unscorable_reason="stand-in could not score this pair"
            )
        return DeduplicationPairResult(
            probability=probability,
            field_comparisons={
                "title": DeduplicationFieldComparison(
                    incoming_value="A complete reference",
                    candidate_value="A complete reference",
                    status=DeduplicationFieldStatus.MATCH,
                    score=1.0,
                )
            },
            suggested_label="duplicate",
        )


SQL_WRITE_METHODS = (
    "add",
    "add_bulk",
    "merge",
    "update_by_pk",
    "bulk_update",
    "bulk_update_by_filter",
    "delete_by_pk",
)
ES_WRITE_METHODS = ("add", "add_bulk", "delete_by_pk")


def _forbid_async_methods(target, method_names: tuple[str, ...]):
    forbidden = {}
    for method_name in method_names:
        method = AsyncMock(
            side_effect=AssertionError(f"assessment called {method_name}")
        )
        setattr(target, method_name, method)
        forbidden[method_name] = method
    return forbidden


def _build_service(
    anti_corruption_service,
    selection: CandidateSelectionResult,
    references: list[Reference],
    probabilities: dict[UUID, float | None],
):
    by_id = {reference.id: reference for reference in references}

    async def get_hydrated(ids, enhancement_types=None, **kwargs):  # noqa: ARG001
        hydrated = []
        for id_ in ids:
            if id_ not in by_id:
                continue
            reference = by_id[id_]
            enhancements = reference.enhancements
            if enhancement_types and enhancements:
                enhancements = [
                    enhancement
                    for enhancement in enhancements
                    if enhancement.content.enhancement_type in enhancement_types
                ]
            hydrated.append(
                reference.model_copy(deep=True, update={"enhancements": enhancements})
            )
        return hydrated

    reader = MagicMock(spec=ReferenceReader)
    reader.get_hydrated = AsyncMock(side_effect=get_hydrated)
    selector = AsyncMock(return_value=selection)
    pair_scorer = FakePairScorer(probabilities)
    service = DeduplicationAssessmentService(
        candidate_selector=selector,
        reference_reader=reader,
        anti_corruption_service=anti_corruption_service,
        pair_scorer=pair_scorer,
    )
    return service, selector, reader, pair_scorer


@pytest.mark.asyncio
async def test_evaluate_supplied_scores_identifier_candidate_and_proposes_it(
    anti_corruption_service,
):
    incoming = _supplied_reference()
    candidate = _reference(community_bound=True)
    identifier = candidate.identifiers[0].identifier
    selected = Candidate(
        reference_id=candidate.id,
        rank=1,
        routes=[
            CandidateIdentifierRoute(
                matched_identifiers=[
                    CandidateIdentifier(
                        identifier=str(identifier.identifier),
                        identifier_type=ExternalIdentifierType.OPEN_ALEX,
                    )
                ]
            )
        ],
    )
    service, selector, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(selected, searchable=False),
        [candidate],
        {candidate.id: 0.91},
    )

    assessment = await service.evaluate_supplied(
        incoming,
        _supplied_input(incoming),
        retrieval_policy=RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1,
        k=7,
    )

    assert assessment.outcome == DeduplicationAssessmentOutcome.PROPOSE_DUPLICATE
    assert assessment.proposed_duplicate_of_id == candidate.id
    assert assessment.threshold_clearing_candidate_ids == [candidate.id]
    assert assessment.scored_candidates[0].candidate.routes[0].type == "identifier"
    assert (
        assessment.scored_candidates[0].pair_result.field_comparisons["title"].score
        == 1
    )
    assert len(pair_scorer.calls) == 1
    assert pair_scorer.calls[0][1].id == candidate.id
    reader.get_hydrated.assert_awaited_once_with(
        [candidate.id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
    )
    request = selector.await_args.args[0]
    assert request.hydrate is False
    assert (
        request.retrieval_policy == RetrievalPolicyName.SOFT_YEAR_DECAY_YEAR_OPTIONAL_V1
    )
    assert request.k == 7
    assert request.input.reference_id is None
    assert (
        request.input.identifiers[0].identifier_type == ExternalIdentifierType.OPEN_ALEX
    )
    assert assessment.model_dump_json()


@pytest.mark.asyncio
async def test_evaluate_scores_all_candidates_and_retains_every_threshold_match(
    anti_corruption_service,
):
    incoming = _reference()
    candidates = [_reference(), _reference(), _reference()]
    selected = [
        Candidate(reference_id=candidate.id, rank=rank, routes=[])
        for rank, candidate in enumerate(candidates, start=1)
    ]
    probabilities = {
        candidates[0].id: 0.95,
        candidates[1].id: 0.2,
        candidates[2].id: 0.85,
    }
    service, selector, _, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(*selected),
        [incoming, *candidates],
        probabilities,
    )

    assessment = await service.evaluate(incoming.id)

    assert assessment.outcome == DeduplicationAssessmentOutcome.NO_PROPOSAL
    assert assessment.proposed_duplicate_of_id is None
    assert assessment.threshold_clearing_candidate_ids == [
        candidates[0].id,
        candidates[2].id,
    ]
    assert [call[1].id for call in pair_scorer.calls] == [
        candidate.id for candidate in candidates
    ]
    assert [
        scored.candidate.reference_id for scored in assessment.scored_candidates
    ] == [candidate.id for candidate in candidates]
    request_input = selector.await_args.args[0].input
    assert request_input.reference_id is None
    assert request_input.excluded_reference_id == incoming.id


@pytest.mark.asyncio
async def test_evaluate_stored_reuses_one_snapshot_for_selection_and_scoring(
    anti_corruption_service,
):
    incoming = _reference(community_bound=True)
    candidate = _reference()
    service, selector, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(Candidate(reference_id=candidate.id, rank=1, routes=[])),
        [incoming, candidate],
        {candidate.id: 0.1},
    )

    await service.evaluate(incoming.id)

    scored_incoming = pair_scorer.calls[0][0]
    assert scored_incoming.enhancements
    assert {
        enhancement.content.enhancement_type
        for enhancement in scored_incoming.enhancements
    } == {EnhancementType.BIBLIOGRAPHIC}
    selection_input = selector.await_args.args[0].input
    assert selection_input.reference_id is None
    assert selection_input.title == "A complete reference"
    assert selection_input.excluded_reference_id == incoming.id
    reader.get_hydrated.assert_any_await(
        [incoming.id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
    )


@pytest.mark.asyncio
async def test_evaluate_supplied_rejects_a_candidate_with_the_incoming_id(
    anti_corruption_service,
):
    incoming = _supplied_reference()
    candidate = _reference()
    candidate.id = incoming.id
    for enhancement in candidate.enhancements or []:
        enhancement.reference_id = incoming.id
    for identifier in candidate.identifiers or []:
        identifier.reference_id = incoming.id
    service, _, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(Candidate(reference_id=incoming.id, rank=1, routes=[])),
        [candidate],
        {incoming.id: 1.0},
    )

    with pytest.raises(DeduplicationValueError, match=str(incoming.id)):
        await service.evaluate_supplied(incoming, _supplied_input(incoming))

    reader.get_hydrated.assert_not_awaited()
    assert pair_scorer.calls == []


@pytest.mark.asyncio
async def test_evaluate_supplied_makes_no_proposal_for_any_unscorable_candidate(
    anti_corruption_service,
):
    incoming = _supplied_reference()
    scored_candidate = _reference()
    unscorable_candidate = _reference()
    candidates = [scored_candidate, unscorable_candidate]
    selected = [
        Candidate(reference_id=candidate.id, rank=rank, routes=[])
        for rank, candidate in enumerate(candidates, start=1)
    ]
    service, _, _, _ = _build_service(
        anti_corruption_service,
        _selection(*selected),
        candidates,
        {
            scored_candidate.id: 0.9,
            unscorable_candidate.id: None,
        },
    )

    assessment = await service.evaluate_supplied(incoming, _supplied_input(incoming))

    assert assessment.outcome == DeduplicationAssessmentOutcome.NO_PROPOSAL
    assert assessment.proposed_duplicate_of_id is None
    assert assessment.threshold_clearing_candidate_ids == [scored_candidate.id]
    assert assessment.unscorable_candidate_ids == [unscorable_candidate.id]
    assert assessment.scored_candidates[0].clears_threshold is True
    assert assessment.scored_candidates[1].clears_threshold is None


@pytest.mark.asyncio
async def test_evaluate_empty_searchable_union_proposes_canonical(
    anti_corruption_service,
):
    incoming = _reference()
    service, _, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(searchable=True),
        [incoming],
        {},
    )

    assessment = await service.evaluate(incoming.id)

    assert assessment.outcome == DeduplicationAssessmentOutcome.PROPOSE_CANONICAL
    assert assessment.proposed_duplicate_of_id is None
    assert assessment.candidate_selection.input_searchability.searchable is True
    assert assessment.threshold_clearing_candidate_ids == []
    assert assessment.scored_candidates == []
    assert pair_scorer.calls == []
    reader.get_hydrated.assert_awaited_once_with(
        [incoming.id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
    )


@pytest.mark.asyncio
async def test_evaluate_empty_unsearchable_union_makes_no_proposal(
    anti_corruption_service,
):
    incoming = _reference()
    service, _, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(searchable=False),
        [incoming],
        {},
    )

    assessment = await service.evaluate(incoming.id)

    assert assessment.outcome == DeduplicationAssessmentOutcome.NO_PROPOSAL
    assert assessment.proposed_duplicate_of_id is None
    assert assessment.candidate_selection.input_searchability.searchable is False
    assert assessment.threshold_clearing_candidate_ids == []
    assert assessment.scored_candidates == []
    assert pair_scorer.calls == []
    reader.get_hydrated.assert_awaited_once_with(
        [incoming.id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
    )


@pytest.mark.asyncio
async def test_evaluate_supplied_scores_the_exact_sdk_reference(
    anti_corruption_service,
):
    """The runner's frozen SDK reference reaches the scorer unchanged."""
    incoming = _supplied_reference()
    candidate = _reference()
    supplied_input = CandidateSelectionInput(
        title="A supplied reference",
        authors=["Jane Doe"],
        publication_year=2025,
    )
    service, selector, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(Candidate(reference_id=candidate.id, rank=1, routes=[])),
        [candidate],
        {candidate.id: 0.1},
    )

    assessment = await service.evaluate_supplied(incoming, supplied_input)

    assert assessment.incoming_reference_id == incoming.id
    assert incoming.enhancements
    assert incoming.enhancements[0].created_at is None
    assert pair_scorer.calls[0][0] is incoming
    assert selector.await_args.args[0].input == supplied_input
    reader.get_hydrated.assert_awaited_once_with(
        [candidate.id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
    )


@pytest.mark.asyncio
async def test_evaluate_supplied_passes_the_callers_exclusion_through(
    anti_corruption_service,
):
    """A held record must not be retrieved as its own candidate."""
    incoming = _supplied_reference()
    held_reference_id = uuid7()
    service, selector, _, _ = _build_service(
        anti_corruption_service,
        _selection(),
        [],
        {},
    )

    await service.evaluate_supplied(
        incoming,
        _supplied_input(incoming, excluded_reference_id=held_reference_id),
    )

    request_input = selector.await_args.args[0].input
    assert request_input.reference_id is None
    assert request_input.excluded_reference_id == held_reference_id


@pytest.mark.asyncio
async def test_evaluate_supplied_reports_retrieval_infrastructure_failure_per_record(
    anti_corruption_service,
):
    """A retrieval blip the repository already translated is one record's failure."""
    incoming = _supplied_reference()
    service, selector, _, pair_scorer = _build_service(
        anti_corruption_service, _selection(), [], {}
    )
    selector.side_effect = ESError("candidate search unavailable (503)")

    with pytest.raises(DeduplicationError):
        await service.evaluate_supplied(incoming, _supplied_input(incoming))

    assert pair_scorer.calls == []


@pytest.mark.asyncio
async def test_evaluate_supplied_reports_hydration_infrastructure_failure_per_record(
    anti_corruption_service,
):
    """A database blip while hydrating candidates is also one record's failure."""
    incoming = _supplied_reference()
    candidate = _reference()
    service, _, reader, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(Candidate(reference_id=candidate.id, rank=1, routes=[])),
        [candidate],
        {candidate.id: 0.9},
    )
    reader.get_hydrated = AsyncMock(
        side_effect=OperationalError("SELECT 1", {}, Exception("connection lost"))
    )

    with pytest.raises(DeduplicationError):
        await service.evaluate_supplied(incoming, _supplied_input(incoming))

    assert pair_scorer.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TypeError("selector called with the wrong shape"), id="type"),
        # A DBAPIError sibling of OperationalError. Catching DBAPIError wholesale
        # would bury a malformed query as a per-record failure on every input.
        pytest.param(
            ProgrammingError("SELECT nope", {}, Exception("column does not exist")),
            id="malformed-query",
        ),
    ],
)
async def test_evaluate_supplied_propagates_defects(anti_corruption_service, error):
    """Only infrastructure failures are localised; a defect still aborts the caller."""
    incoming = _supplied_reference()
    service, selector, _, _ = _build_service(
        anti_corruption_service, _selection(), [], {}
    )
    selector.side_effect = error

    with pytest.raises(type(error)):
        await service.evaluate_supplied(incoming, _supplied_input(incoming))


@pytest.mark.asyncio
async def test_evaluate_supplied_fails_when_candidate_union_cannot_be_hydrated(
    anti_corruption_service,
):
    incoming = _supplied_reference()
    missing_id = uuid7()
    service, _, _, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(Candidate(reference_id=missing_id, rank=1, routes=[])),
        [],
        {missing_id: 0.9},
    )

    with pytest.raises(DeduplicationError, match=str(missing_id)):
        await service.evaluate_supplied(incoming, _supplied_input(incoming))

    assert pair_scorer.calls == []


@pytest.mark.asyncio
async def test_evaluate_fails_when_stored_incoming_cannot_be_hydrated(
    anti_corruption_service,
):
    reference_id = uuid7()
    service, selector, _, pair_scorer = _build_service(
        anti_corruption_service,
        _selection(),
        [],
        {},
    )

    with pytest.raises(NotFoundError, match=str(reference_id)) as exc_info:
        await service.evaluate(reference_id)

    assert isinstance(exc_info.value, DeduplicationError)
    selector.assert_not_awaited()
    assert pair_scorer.calls == []


@pytest.mark.asyncio
async def test_evaluate_supplied_runs_real_candidate_union_without_side_effects(
    anti_corruption_service,
    fake_repository,
    fake_uow,
):
    incoming = _supplied_reference()
    candidate = _reference(community_bound=True)
    candidate.identifiers = [
        LinkedExternalIdentifierFactory.build(
            reference_id=candidate.id,
            identifier=incoming.identifiers[0],
        )
    ]
    references = fake_repository([candidate])
    references.find_with_identifiers = AsyncMock(return_value=[candidate])
    references.get_hydrated = AsyncMock(return_value=[candidate])
    forbidden_reference_writes = _forbid_async_methods(references, SQL_WRITE_METHODS)
    decisions = fake_repository()
    forbidden_decision_writes = _forbid_async_methods(decisions, SQL_WRITE_METHODS)
    sql_uow = fake_uow(
        references=references,
        reference_duplicate_decisions=decisions,
    )
    sql_uow.commit = AsyncMock(
        side_effect=AssertionError("assessment committed the SQL unit of work")
    )
    es_uow = MagicMock()
    es_references = MagicMock()
    es_references.get_current_index_name = AsyncMock(return_value="reference_v3")
    es_references.search_for_candidate_canonicals = AsyncMock(
        return_value=CandidateCanonicalSearchResult(
            hits=[],
            total=ESSearchTotal(value=0, relation="eq"),
            took_ms=1,
        )
    )
    forbidden_es_writes = _forbid_async_methods(es_references, ES_WRITE_METHODS)
    es_uow.references = es_references
    es_uow.commit = AsyncMock(
        side_effect=AssertionError("assessment committed the ES unit of work")
    )
    candidate_service = DeduplicationService(
        anti_corruption_service,
        sql_uow,
        es_uow,
    )
    pair_scorer = FakePairScorer({candidate.id: 0.9})
    assessor = DeduplicationAssessmentService(
        candidate_selector=candidate_service.get_deduplication_candidates,
        reference_reader=references,
        anti_corruption_service=anti_corruption_service,
        pair_scorer=pair_scorer,
    )

    assessment = await assessor.evaluate_supplied(incoming, _supplied_input(incoming))

    assert assessment.proposed_duplicate_of_id == candidate.id
    assert assessment.scored_candidates[0].candidate.routes[0].type == "identifier"
    assert len(pair_scorer.calls) == 1
    references.get_hydrated.assert_awaited_once_with(
        [candidate.id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
    )
    for method in (
        *forbidden_reference_writes.values(),
        *forbidden_decision_writes.values(),
        *forbidden_es_writes.values(),
    ):
        method.assert_not_awaited()
    sql_uow.commit.assert_not_awaited()
    es_uow.commit.assert_not_awaited()
