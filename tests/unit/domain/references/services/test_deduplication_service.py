import datetime
import itertools
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from destiny_sdk.enhancements import Authorship
from destiny_sdk.identifiers import OtherIdentifier

from app.core.config import Environment
from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import (
    Candidate,
    CandidateSelectionDiagnostics,
    CandidateSelectionResult,
    DuplicateDecisionAuthority,
    DuplicateDecisionTrigger,
    DuplicateDetermination,
    ExternalIdentifierType,
    InputSearchability,
    LinkedExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
    RetrievalPolicyName,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_service import DeduplicationService
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
    OpenAlexIdentifierFactory,
    OtherIdentifierFactory,
    RawEnhancementFactory,
    ReferenceFactory,
)
from tests.unit.domain.conftest import link_fake_repos


def _mock_candidate_selection(service: DeduplicationService, *candidate_ids) -> None:
    """Configure repositories used by the shared read-only candidate selector."""
    service.sql_uow.references.find_with_identifiers = AsyncMock(  # type: ignore[method-assign]
        return_value=[]
    )
    service.es_uow = MagicMock()
    service.es_uow.references.get_current_index_name = AsyncMock(
        return_value="reference_v3"
    )
    service.es_uow.references.search_for_candidate_canonicals = AsyncMock(
        return_value=CandidateCanonicalSearchResult(
            hits=[ESScoreResult(id=id_, score=1.0) for id_ in candidate_ids],
            total=ESSearchTotal(value=len(candidate_ids), relation="eq"),
            took_ms=1,
        )
    )


def _candidate_selection(*candidate_ids) -> CandidateSelectionResult:
    """Build the retrieval contract consumed by temporary determination tests."""
    return CandidateSelectionResult(
        retrieval_policy=RetrievalPolicyName.CANDIDATE_SELECTION_V1,
        index_version="reference_v3",
        k_requested=10,
        input_searchability=InputSearchability(searchable=True, reason="ok"),
        diagnostics=CandidateSelectionDiagnostics(candidate_count=len(candidate_ids)),
        candidates=[
            Candidate(reference_id=id_, rank=rank, routes=[])
            for rank, id_ in enumerate(candidate_ids, start=1)
        ],
    )


@pytest.fixture
def reference() -> Reference:
    return ReferenceFactory.build(visibility="public")


@pytest.fixture
def reference_with_non_other_identifier(reference: Reference) -> Reference:
    assert reference.identifiers
    reference.identifiers.append(
        LinkedExternalIdentifierFactory.build(
            identifier=OpenAlexIdentifierFactory.build(),
            reference_id=reference.id,
        )
    )
    return reference


@pytest.fixture
def searchable_reference(reference: Reference) -> Reference:
    return reference.model_copy(
        update={
            "enhancements": [
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        authorship=[
                            Authorship(display_name="John Doe", position="first")
                        ],
                        publication_year=2025,
                        title="Maybe a duplicate reference, maybe not",
                    ),
                )
            ]
        }
    )


@pytest.fixture
def anti_corruption_service():
    return MagicMock(spec=ReferenceAntiCorruptionService)


@pytest.mark.asyncio
async def test_find_exact_duplicate_happy_path(
    reference_with_non_other_identifier,
    anti_corruption_service,
    fake_uow,
    fake_repository,
):
    candidate = reference_with_non_other_identifier.model_copy(
        update={"id": uuid7()},
    )
    repo = fake_repository([candidate])
    uow = fake_uow(references=repo)
    uow.references.find_with_identifiers = AsyncMock(return_value=[candidate])
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())
    result = await service.find_exact_duplicate(reference_with_non_other_identifier)
    assert result == candidate
    # No longer a subset
    result = await service.find_exact_duplicate(
        reference_with_non_other_identifier.model_copy(update={"visibility": "hidden"})
    )
    assert not result


@pytest.mark.asyncio
async def test_find_exact_duplicate_no_identifiers(
    anti_corruption_service, fake_uow, fake_repository
):
    ref = Reference(id=uuid7(), identifiers=None)
    uow = fake_uow(references=fake_repository())
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())
    with pytest.raises(DeduplicationValueError):
        await service.find_exact_duplicate(ref)


@pytest.mark.asyncio
async def test_find_exact_duplicate_only_other_identifier(
    anti_corruption_service, fake_uow, fake_repository
):
    ref = Reference(
        id=uuid7(),
        identifiers=[
            LinkedExternalIdentifier(
                identifier=OtherIdentifier(
                    identifier="otherid",
                    identifier_type=ExternalIdentifierType.OTHER,
                    other_identifier_name="other_name",
                ),
                reference_id=uuid7(),
            )
        ],
    )
    uow = fake_uow(references=fake_repository())
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())
    result = await service.find_exact_duplicate(ref)
    assert result is None


@pytest.mark.asyncio
async def test_find_exact_duplicate_excludes_other_identifiers_from_query(
    anti_corruption_service, fake_uow, fake_repository
):
    """Verify that 'other' type identifiers are excluded from the SQL query.

    The ix_external_identifier_type_other index has poor selectivity at scale,
    causing multi-second scans. Filtering to non-other identifiers for the SQL
    candidate search avoids this while is_superset still validates the full match.
    See #604.
    """
    open_alex_id = OpenAlexIdentifierFactory.build()
    doi_id = DOIIdentifierFactory.build()
    other_id = OtherIdentifierFactory.build()

    ref = ReferenceFactory.build(
        identifiers=[
            LinkedExternalIdentifierFactory.build(identifier=open_alex_id),
            LinkedExternalIdentifierFactory.build(identifier=doi_id),
            LinkedExternalIdentifierFactory.build(identifier=other_id),
        ],
    )
    # Candidate is a superset (has all three identifiers including other)
    candidate = ref.model_copy(update={"id": uuid7()})

    uow = fake_uow(references=fake_repository([candidate]))
    uow.references.find_with_identifiers = AsyncMock(return_value=[candidate])
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())

    result = await service.find_exact_duplicate(ref)
    assert result == candidate

    # Verify only non-other identifiers were passed to find_with_identifiers
    call_args = uow.references.find_with_identifiers.call_args
    queried_identifiers = call_args[0][0]
    queried_types = {i.identifier_type for i in queried_identifiers}
    assert ExternalIdentifierType.OTHER not in queried_types
    assert len(queried_identifiers) == 2  # open_alex + doi, not 3


@pytest.mark.asyncio
async def test_find_exact_duplicate_updated_enhancement(
    anti_corruption_service, fake_uow, fake_repository
):
    bibliography = BibliographicMetadataEnhancementFactory.build(title="A title")
    raw_enhancement = RawEnhancementFactory.build()
    ref = ReferenceFactory.build(
        identifiers=[
            # Ensure we have at least one non-other identifier
            LinkedExternalIdentifierFactory.build(
                identifier=OpenAlexIdentifierFactory.build()
            ),
            # Build another random one
            LinkedExternalIdentifierFactory.build(),
        ],
        enhancements=[
            EnhancementFactory.build(
                content=bibliography,
            ),
            EnhancementFactory.build(
                content=raw_enhancement,
            ),
        ],
    )
    repo = fake_repository([ref])
    uow = fake_uow(references=repo)
    uow.references.find_with_identifiers = AsyncMock(return_value=[ref])
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())

    # Change non-meaningful field
    updated_ref = ref.model_copy(deep=True)
    updated_ref.enhancements[0].content.updated_date += datetime.timedelta(days=1)
    updated_ref.enhancements[1].content.source_export_date += datetime.timedelta(days=1)
    result = await service.find_exact_duplicate(updated_ref)
    assert result == ref

    # Change something meaningful
    updated_ref.enhancements[0].content.title = "A different title"
    result = await service.find_exact_duplicate(updated_ref)
    assert result is None


@pytest.mark.asyncio
async def test_register_pending_import_decision(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository()),
        fake_uow(),
    )
    result = await service.register_pending_import_decision(reference.id)
    assert result.reference_id == reference.id
    assert result.duplicate_determination == DuplicateDetermination.PENDING
    assert result.decision_authority == DuplicateDecisionAuthority.SYSTEM
    assert result.decision_trigger == DuplicateDecisionTrigger.IMPORT
    assert result.canonical_reference_id is None
    # Inactive is what makes the direct insert safe: it displaces nothing.
    assert not result.active_decision


@pytest.mark.asyncio
async def test_register_exact_duplicate_import_decision(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository()),
        fake_uow(),
    )
    canonical_id = uuid7()

    result = await service.register_exact_duplicate_import_decision(
        reference.id, canonical_id
    )

    assert result.reference_id == reference.id
    assert result.duplicate_determination == DuplicateDetermination.EXACT_DUPLICATE
    assert result.canonical_reference_id == canonical_id
    assert result.decision_authority == DuplicateDecisionAuthority.SYSTEM
    assert result.decision_trigger == DuplicateDecisionTrigger.IMPORT
    assert result.active_decision


@pytest.mark.asyncio
async def test_unsearchable_reference_returns_empty_selection_without_es_search(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    reference.enhancements = []
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(references=fake_repository([reference])),
        fake_uow(),
    )

    _mock_candidate_selection(service)
    result = await service.select_candidate_canonicals(reference.id)

    assert result.retrieval_policy.value == "candidate_selection_v1"
    assert not result.input_searchability.searchable
    assert not result.candidates
    service.es_uow.references.search_for_candidate_canonicals.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_candidate_canonicals_returns_unhydrated_provenance(
    searchable_reference, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(references=fake_repository([searchable_reference])),
        fake_uow(),
    )

    candidate_id = uuid7()
    _mock_candidate_selection(service, candidate_id)
    result = await service.select_candidate_canonicals(searchable_reference.id)

    assert result.retrieval_policy.value == "candidate_selection_v1"
    assert result.index_version == "reference_v3"
    assert result.k_requested == 10
    assert [candidate.reference_id for candidate in result.candidates] == [candidate_id]
    assert result.candidates[0].routes[0].type == "elasticsearch"
    assert result.candidates[0].routes[0].policy == "candidate_selection_v1"
    assert result.candidates[0].reference is None
    search_call = service.es_uow.references.search_for_candidate_canonicals.await_args
    assert search_call.kwargs["track_total_hits"] is True


@pytest.mark.asyncio
async def test_searchable_reference_returns_empty_selection_after_es_search(
    searchable_reference, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(references=fake_repository([searchable_reference])),
        fake_uow(),
    )
    _mock_candidate_selection(service)
    result = await service.select_candidate_canonicals(searchable_reference.id)

    assert result.input_searchability.searchable
    assert not result.candidates
    service.es_uow.references.search_for_candidate_canonicals.assert_awaited()


@pytest.mark.asyncio
async def test_placeholder_selects_first_candidate_in_test_environment(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository([decision])),
        fake_uow(),
    )
    first_candidate_id = uuid7()

    result = await service.determine_canonical_from_candidates(
        decision,
        _candidate_selection(first_candidate_id, uuid7()),
    )

    assert result.duplicate_determination is DuplicateDetermination.DUPLICATE
    assert result.canonical_reference_id == first_candidate_id


@pytest.mark.asyncio
async def test_placeholder_marks_searchable_empty_selection_canonical_in_tests(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository([decision])),
        fake_uow(),
    )

    result = await service.determine_canonical_from_candidates(
        decision,
        _candidate_selection(),
    )

    assert result.duplicate_determination is DuplicateDetermination.CANONICAL


@pytest.mark.asyncio
async def test_placeholder_marks_unsearchable_selection_unsearchable_in_tests(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository([decision])),
        fake_uow(),
    )
    selection = _candidate_selection().model_copy(
        update={
            "input_searchability": InputSearchability(
                searchable=False, reason="missing title"
            )
        }
    )

    result = await service.determine_canonical_from_candidates(decision, selection)

    assert result.duplicate_determination is DuplicateDetermination.UNSEARCHABLE


@pytest.mark.asyncio
async def test_placeholder_never_selects_candidate_outside_test_environment(
    reference, anti_corruption_service, fake_uow, fake_repository, monkeypatch
):
    from app.domain.references.services import deduplication_service as dedup_module

    monkeypatch.setattr(dedup_module.settings, "env", Environment.LOCAL)
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository([decision])),
        fake_uow(),
    )

    result = await service.determine_canonical_from_candidates(
        decision,
        _candidate_selection(uuid7()),
    )

    assert result.duplicate_determination is DuplicateDetermination.UNSEARCHABLE
    assert result.canonical_reference_id is None


@pytest.mark.asyncio
async def test_map_duplicate_decision_activates_new_duplicate(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and decision
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.duplicate_decision = None
    reference.has_duplicates = False

    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
    )

    ref_repo = fake_repository([reference, canonical])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    out_decision, decision_changed, _ = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == canonical.id
    assert decision_changed
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
async def test_map_duplicate_decision_reports_matching_active_decision_unchanged(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and decision
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.has_duplicates = False
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
    )

    ref_repo = fake_repository([reference, canonical])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    out_decision, decision_changed, _ = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == canonical.id
    assert decision_changed is False
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
async def test_map_duplicate_decision_retains_person_active_decision(
    fake_uow, fake_repository, anti_corruption_service
):
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.has_duplicates = False
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        active_decision=True,
        decision_authority=DuplicateDecisionAuthority.PERSON,
        decision_trigger=DuplicateDecisionTrigger.MANUAL_API,
    )
    reference.duplicate_decision = active_decision
    proposal = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
        detail="Automatic assessment reason.",
        decision_authority=DuplicateDecisionAuthority.SYSTEM,
        decision_trigger=DuplicateDecisionTrigger.EXPLICIT_RERUN,
    )

    decision_repo = fake_repository([active_decision, proposal])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=fake_repository([reference, canonical]),
            reference_duplicate_decisions=decision_repo,
        ),
        fake_uow(),
    )

    result, decision_changed, previous = await service.map_duplicate_decision(proposal)

    assert result.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert result.canonical_reference_id == canonical.id
    assert "Proposed determination: duplicate." in result.detail
    assert "Automatic assessment reason." in result.detail
    assert not result.active_decision
    assert active_decision.active_decision
    assert decision_changed is False
    assert previous is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unclassified_determination",
    [
        DuplicateDetermination.CANONICAL,
        DuplicateDetermination.UNSEARCHABLE,
    ],
)
async def test_map_duplicate_decision_replaces_unclassified_active_decision(
    unclassified_determination, fake_uow, fake_repository, anti_corruption_service
):
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.has_duplicates = False
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=unclassified_determination,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision
    proposal = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
        decision_authority=DuplicateDecisionAuthority.SYSTEM,
        decision_trigger=DuplicateDecisionTrigger.IMPORT,
    )

    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=fake_repository([reference, canonical]),
            reference_duplicate_decisions=fake_repository([active_decision, proposal]),
        ),
        fake_uow(),
    )

    result, decision_changed, previous = await service.map_duplicate_decision(proposal)

    assert result.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert result.active_decision
    assert not active_decision.active_decision
    assert decision_changed is True
    assert previous is active_decision


@pytest.mark.asyncio
async def test_map_duplicate_decision_deactivates_blocked_proposal(
    fake_uow, fake_repository, anti_corruption_service
):
    """A proposal built active must not stay active once decoupled, or it
    collides with the retained decision on the one-active-decision index.
    """
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.has_duplicates = False
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        active_decision=True,
        decision_authority=DuplicateDecisionAuthority.PERSON,
        decision_trigger=DuplicateDecisionTrigger.MANUAL_API,
    )
    reference.duplicate_decision = active_decision
    proposal = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
        active_decision=True,
        decision_authority=DuplicateDecisionAuthority.SYSTEM,
        decision_trigger=DuplicateDecisionTrigger.IMPORT,
    )

    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=fake_repository([reference, canonical]),
            reference_duplicate_decisions=fake_repository([active_decision, proposal]),
        ),
        fake_uow(),
    )

    result, _, _ = await service.map_duplicate_decision(proposal)

    assert result.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert not result.active_decision
    assert active_decision.active_decision


@pytest.mark.asyncio
async def test_map_duplicate_decision_blocks_identical_automatic_result(
    fake_uow, fake_repository, anti_corruption_service
):
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.has_duplicates = False
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        active_decision=True,
        decision_authority=DuplicateDecisionAuthority.PERSON,
        decision_trigger=DuplicateDecisionTrigger.MANUAL_API,
    )
    reference.duplicate_decision = active_decision
    proposal = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        decision_authority=DuplicateDecisionAuthority.SYSTEM,
        decision_trigger=DuplicateDecisionTrigger.IMPORT,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=fake_repository([reference]),
            reference_duplicate_decisions=fake_repository([active_decision, proposal]),
        ),
        fake_uow(),
    )

    result, decision_changed, previous = await service.map_duplicate_decision(proposal)

    assert result.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert active_decision.active_decision
    assert not result.active_decision
    assert decision_changed is False
    assert previous is None


@pytest.mark.asyncio
async def test_determine_returns_terminal_decision_unchanged(
    fake_uow, fake_repository, anti_corruption_service
):
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.duplicate_decision = None

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
    )
    ref_repo = fake_repository([reference])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    determined = await service.determine_canonical_from_candidates(
        decision, _candidate_selection()
    )
    assert determined == decision


@pytest.mark.asyncio
async def test_map_duplicate_decision_decouples_duplicate_becoming_canonical(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was DUPLICATE, now CANONICAL)
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=uuid7(),
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
    )

    ref_repo = fake_repository([reference])
    dec_repo = fake_repository([active_decision, decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    out_decision, decision_changed, _ = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert not out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )


@pytest.mark.asyncio
async def test_map_duplicate_decision_decouples_changed_canonical_target(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was DUPLICATE of A, now DUPLICATE of B)
    canonical_a = MagicMock(spec=Reference)
    canonical_a.id = uuid7()
    canonical_a.is_canonical = True

    canonical_b = MagicMock(spec=Reference)
    canonical_b.id = uuid7()
    canonical_b.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_a.id,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_b.id,
    )

    ref_repo = fake_repository([reference, canonical_a, canonical_b])
    dec_repo = fake_repository([active_decision, decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    out_decision, decision_changed, _ = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed


@pytest.mark.asyncio
async def test_map_duplicate_decision_decouples_reference_with_duplicates(
    fake_uow, fake_repository, anti_corruption_service
):
    """Reference with existing duplicates cannot become a duplicate itself."""
    candidate = MagicMock(spec=Reference)
    candidate.id = uuid7()
    candidate.is_canonical = True

    existing_duplicate = Reference(
        id=uuid7(),
        identifiers=[],
        enhancements=[],
    )
    reference = Reference(
        id=uuid7(),
        identifiers=[],
        enhancements=[],
        duplicate_decision=None,
        duplicate_references=[existing_duplicate],
    )

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=candidate.id,
    )

    ref_repo = fake_repository([reference, candidate])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )

    out_decision, decision_changed, _ = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert "Decouple reason: Reference has existing duplicates" in out_decision.detail
    assert decision_changed


@pytest.mark.asyncio
async def test_map_duplicate_decision_rejects_self_reference(
    fake_uow, fake_repository, anti_corruption_service
):
    """Cannot mark a reference as a duplicate of itself."""
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=reference.id,
    )

    ref_repo = fake_repository([reference])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )

    with pytest.raises(DeduplicationValueError, match="duplicate of itself"):
        await service.map_duplicate_decision(decision)


@pytest.mark.asyncio
async def test_map_duplicate_decision_replaces_active_canonical_decision(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was CANONICAL, now DUPLICATE)
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    reference.has_duplicates = False
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        canonical_reference_id=None,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
    )

    ref_repo = fake_repository([reference, canonical])
    dec_repo = fake_repository([active_decision, decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    out_decision, decision_changed, _ = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert decision_changed
    old_decision = await dec_repo.get_by_pk(active_decision.id)
    assert not old_decision.active_decision
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_decision",
    [
        None,
        ReferenceDuplicateDecision(
            reference_id=uuid7(),
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            canonical_reference_id=uuid7(),
            active_decision=True,
        ),
    ],
    ids=["undecided", "already-duplicate"],
)
async def test_map_duplicate_decision_rejects_non_canonical_target(
    target_decision,
    fake_uow,
    fake_repository,
    anti_corruption_service,
):
    """Mapping a duplicate to a non-canonical reference should be rejected."""
    target_ref = MagicMock(spec=Reference)
    target_ref.id = uuid7()
    target_ref.duplicate_decision = target_decision
    target_ref.is_canonical = False if target_decision else None

    reference_b = MagicMock(spec=Reference)
    reference_b.id = uuid7()
    reference_b.duplicate_decision = None

    decision = ReferenceDuplicateDecision(
        reference_id=reference_b.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=target_ref.id,
    )

    ref_repo = fake_repository([target_ref, reference_b])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(references=ref_repo, reference_duplicate_decisions=dec_repo),
        fake_uow(),
    )

    with pytest.raises(DeduplicationValueError, match="non-canonical"):
        await service.map_duplicate_decision(decision)


class TestShortcutDeduplication:
    """
    Test the five cases listed in the docstring of
    ``DeduplicationService.shortcut_deduplication_using_identifiers``.
    """

    @pytest.fixture
    def trusted_identifier(self) -> LinkedExternalIdentifier:
        return LinkedExternalIdentifierFactory.build(
            identifier=OpenAlexIdentifierFactory.build(),
        )

    def _get_existing_canonical_and_duplicate(
        self, trusted_identifier: LinkedExternalIdentifier
    ) -> tuple[Reference, Reference]:
        canonical: Reference = ReferenceFactory.build()
        duplicate: Reference = ReferenceFactory.build(
            canonical_reference=canonical,
        )
        assert duplicate.identifiers
        duplicate.identifiers.append(trusted_identifier)
        duplicate.canonical_reference = canonical

        duplicate_duplicates_canonical = ReferenceDuplicateDecision(
            reference_id=duplicate.id,
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            canonical_reference_id=canonical.id,
            active_decision=True,
        )
        canonical_is_canonical = ReferenceDuplicateDecision(
            reference_id=canonical.id,
            duplicate_determination=DuplicateDetermination.CANONICAL,
            active_decision=True,
        )

        canonical.duplicate_decision = canonical_is_canonical
        duplicate.duplicate_decision = duplicate_duplicates_canonical

        return canonical, duplicate

    @pytest.fixture
    def existing_canonical_and_duplicate(
        self, trusted_identifier: LinkedExternalIdentifier
    ) -> tuple[Reference, Reference]:
        return self._get_existing_canonical_and_duplicate(trusted_identifier)

    async def test_shortcut_deduplication_case_a(
        self,
        existing_canonical_and_duplicate: tuple[Reference, Reference],
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Test that shortcut deduplication marks the given reference as duplicate
        of the existing duplicate relationship graph's canonical reference.
        """
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        canonical, duplicate = existing_canonical_and_duplicate

        # Should work regardless of which is found
        for found in [canonical, duplicate]:
            repo = fake_repository([canonical, duplicate, incoming])
            decision = ReferenceDuplicateDecision(
                reference_id=incoming.id,
                duplicate_determination=DuplicateDetermination.PENDING,
            )
            duplicate_repo = fake_repository(
                [decision, canonical.duplicate_decision, duplicate.duplicate_decision]
            )
            uow = fake_uow(
                references=repo, reference_duplicate_decisions=duplicate_repo
            )
            service = DeduplicationService(
                anti_corruption_service,
                uow,
                fake_uow(),
            )
            uow.references.find_with_identifiers = AsyncMock(return_value=[found])

            results = await service.shortcut_deduplication_using_identifiers(
                decision,
                trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
            )
            assert results
            result = results[0]
            assert result.id == decision.id
            assert result.reference_id == incoming.id
            assert result.duplicate_determination == DuplicateDetermination.DUPLICATE
            assert result.canonical_reference_id == canonical.id
            assert result.detail == "Shortcutted with trusted identifier(s)"

    async def test_shortcut_deduplication_case_b(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        existing_canonical_and_duplicate: tuple[Reference, Reference],
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Test that shortcut deduplication marks the given reference as decoupled
        when multiple duplicate relationship graphs are found.
        """
        canonical_1, duplicate_1 = existing_canonical_and_duplicate
        canonical_2, duplicate_2 = self._get_existing_canonical_and_duplicate(
            trusted_identifier
        )
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        for found in itertools.product(
            (duplicate_1, canonical_1), (duplicate_2, canonical_2)
        ):
            repo = fake_repository([duplicate_1, duplicate_2, incoming])

            decision = ReferenceDuplicateDecision(
                reference_id=incoming.id,
                duplicate_determination=DuplicateDetermination.PENDING,
            )
            duplicate_repo = fake_repository(
                [
                    decision,
                    canonical_1.duplicate_decision,
                    duplicate_1.duplicate_decision,
                    canonical_2.duplicate_decision,
                    duplicate_2.duplicate_decision,
                ]
            )
            uow = fake_uow(
                references=repo, reference_duplicate_decisions=duplicate_repo
            )
            service = DeduplicationService(
                anti_corruption_service,
                uow,
                fake_uow(),
            )

            uow.references.find_with_identifiers = AsyncMock(return_value=found)
            results = await service.shortcut_deduplication_using_identifiers(
                decision,
                trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
            )
            assert results
            result = results[0]
            assert result.reference_id == incoming.id
            assert result.duplicate_determination == DuplicateDetermination.DECOUPLED
            assert result.detail
            assert result.detail.startswith(
                "Multiple canonical references found for trusted unique identifiers."
            )

    async def test_shortcut_deduplication_case_c(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Test that shortcut deduplication builds a new duplicate relationship graph
        on previously undeduplicated references.
        """
        existing_1: Reference = ReferenceFactory.build()
        assert existing_1.identifiers
        existing_1.identifiers.append(trusted_identifier)
        existing_2: Reference = ReferenceFactory.build()
        assert existing_2.identifiers
        existing_2.identifiers.append(trusted_identifier)
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        repo = fake_repository([existing_1, existing_2, incoming])
        decision = ReferenceDuplicateDecision(
            reference_id=incoming.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        duplicate_repo = fake_repository([decision])
        duplicate_repo.get_active_decision_determinations = AsyncMock(return_value={})
        link_fake_repos(
            duplicate_repo,
            repo,
            fk="reference_id",
            attr="duplicate_decision",
            filter_field="active_decision",
            filter_value=True,
        )
        uow = fake_uow(references=repo, reference_duplicate_decisions=duplicate_repo)
        uow.references.find_with_identifiers = AsyncMock(
            return_value=[existing_1, existing_2]
        )
        service = DeduplicationService(
            anti_corruption_service,
            uow,
            fake_uow(),
        )

        results = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )
        assert results
        assert len(results) == 3
        result = results[0]
        assert result.reference_id == incoming.id
        assert result.duplicate_determination == DuplicateDetermination.CANONICAL
        assert result.detail == "Shortcutted with trusted identifier(s)"

        for existing_result in results[1:]:
            assert existing_result
            assert (
                existing_result.duplicate_determination
                == DuplicateDetermination.DUPLICATE
            )
            assert existing_result.canonical_reference_id == incoming.id
            assert (
                existing_result.detail
                == f"Shortcutted via proxy reference {incoming.id} "
                "with trusted identifier(s)"
            )

    async def test_shortcut_deduplication_case_d(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        existing_canonical_and_duplicate: tuple[Reference, Reference],
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Test that shortcut deduplication marks non-graph references as duplicates
        of the graph's canonical reference.
        """
        canonical, duplicate = existing_canonical_and_duplicate
        existing_undeduplicated = ReferenceFactory.build()
        assert existing_undeduplicated.identifiers
        existing_undeduplicated.identifiers.append(trusted_identifier)
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        repo = fake_repository(
            [canonical, duplicate, existing_undeduplicated, incoming]
        )
        decision = ReferenceDuplicateDecision(
            reference_id=incoming.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        duplicate_repo = fake_repository([decision])
        duplicate_repo.get_active_decision_determinations = AsyncMock(return_value={})
        uow = fake_uow(references=repo, reference_duplicate_decisions=duplicate_repo)
        service = DeduplicationService(
            anti_corruption_service,
            uow,
            fake_uow(),
        )
        uow.references.find_with_identifiers = AsyncMock(
            return_value=[duplicate, existing_undeduplicated]
        )

        results = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )
        assert results
        result = results[0]
        assert result.reference_id == incoming.id
        assert result.duplicate_determination == DuplicateDetermination.DUPLICATE
        assert result.canonical_reference_id == canonical.id
        assert result.detail == "Shortcutted with trusted identifier(s)"

        existing_result = await duplicate_repo.find(
            reference_id=existing_undeduplicated.id
        )
        assert existing_result
        assert (
            existing_result[0].duplicate_determination
            == DuplicateDetermination.DUPLICATE
        )
        assert existing_result[0].canonical_reference_id == canonical.id
        assert (
            existing_result[0].detail
            == f"Shortcutted via proxy reference {incoming.id} "
            "with trusted identifier(s)"
        )

    async def test_shortcut_marks_canonical_when_trusted_identifier_has_no_matches(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Trusted identifiers with no matches should mark CANONICAL immediately.

        Justification for skipping ES deduplication:
        - Trusted identifiers (e.g., OpenAlex W-ID) are unique within source
        - No matching references means the reference is definitively unique
        - ES fuzzy matching would be redundant and could create false
          duplicate relationships based on similar titles/authors when we
          already have certainty from the identifier

        Previously this would return None (fall through to ES). Now it marks
        as CANONICAL immediately, avoiding unnecessary ES queries.
        """
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        repo = fake_repository([incoming])
        decision = ReferenceDuplicateDecision(
            reference_id=incoming.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        duplicate_repo = fake_repository([decision])
        uow = fake_uow(references=repo, reference_duplicate_decisions=duplicate_repo)
        service = DeduplicationService(
            anti_corruption_service,
            uow,
            fake_uow(),
        )
        uow.references.find_with_identifiers = AsyncMock(return_value=[])

        results = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )

        # Key assertion: we get a result instead of None (fall through case)
        assert results is not None, (
            "Trusted identifier with no matches should shortcut to CANONICAL, "
            "not fall through to ES deduplication"
        )
        assert len(results) == 1
        assert results[0].duplicate_determination == DuplicateDetermination.CANONICAL
        assert results[0].detail == (
            "New reference with trusted identifier(s), no existing matches"
        )

    async def test_shortcut_deduplication_case_e_no_trusted_identifiers(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """Falls through to ES when no trusted identifier types are provided."""
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        repo = fake_repository([incoming])
        decision = ReferenceDuplicateDecision(
            reference_id=incoming.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        duplicate_repo = fake_repository([decision])
        uow = fake_uow(references=repo, reference_duplicate_decisions=duplicate_repo)
        service = DeduplicationService(
            anti_corruption_service,
            uow,
            fake_uow(),
        )
        uow.references.find_with_identifiers = AsyncMock(return_value=[])

        # No trusted identifiers provided - falls through to ES deduplication
        result = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types=set(),
        )
        assert (
            result is None
        ), "Should fall through to ES when no trusted types provided"

    async def test_shortcut_deduplication_rejects_non_pending(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """Rejects shortcut on non-pending duplicate decisions."""
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        repo = fake_repository([incoming])
        decision = ReferenceDuplicateDecision(
            reference_id=incoming.id,
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            canonical_reference_id=uuid7(),
            active_decision=True,
        )
        duplicate_repo = fake_repository([decision])
        uow = fake_uow(references=repo, reference_duplicate_decisions=duplicate_repo)
        service = DeduplicationService(
            anti_corruption_service,
            uow,
            fake_uow(),
        )

        with pytest.raises(DeduplicationValueError):
            await service.shortcut_deduplication_using_identifiers(
                decision,
                trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
            )

    async def test_shortcut_skips_candidate_with_existing_decision(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Race condition guard: if another worker already created a decision for
        an undeduplicated candidate, skip the side-effect for that candidate.
        """
        existing_1: Reference = ReferenceFactory.build()
        assert existing_1.identifiers
        existing_1.identifiers.append(trusted_identifier)
        existing_2: Reference = ReferenceFactory.build()
        assert existing_2.identifiers
        existing_2.identifiers.append(trusted_identifier)
        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers
        incoming.identifiers.append(trusted_identifier)

        repo = fake_repository([existing_1, existing_2, incoming])
        decision = ReferenceDuplicateDecision(
            reference_id=incoming.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        duplicate_repo = fake_repository([decision])

        # existing_1 has no decision — side-effect should proceed
        # existing_2 already has CANONICAL — side-effect should be skipped
        duplicate_repo.get_active_decision_determinations = AsyncMock(
            return_value={
                existing_2.id: DuplicateDetermination.CANONICAL,
            }
        )
        link_fake_repos(
            duplicate_repo,
            repo,
            fk="reference_id",
            attr="duplicate_decision",
            filter_field="active_decision",
            filter_value=True,
        )

        uow = fake_uow(references=repo, reference_duplicate_decisions=duplicate_repo)
        uow.references.find_with_identifiers = AsyncMock(
            return_value=[existing_1, existing_2]
        )
        service = DeduplicationService(
            anti_corruption_service,
            uow,
            fake_uow(),
        )

        results = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )
        assert results
        # Incoming becomes canonical + only existing_1 gets a side-effect decision
        assert len(results) == 2
        assert results[0].reference_id == incoming.id
        assert results[0].duplicate_determination == DuplicateDetermination.CANONICAL

        assert results[1].reference_id == existing_1.id
        assert results[1].duplicate_determination == DuplicateDetermination.DUPLICATE
        assert results[1].canonical_reference_id == incoming.id

        # existing_2 already handled by another worker — no side-effect
        assert all(r.reference_id != existing_2.id for r in results)
        # Verify the bulk guard was called once with all candidate IDs
        duplicate_repo.get_active_decision_determinations.assert_awaited_once()

    async def test_shortcut_deduplication_multiple_decision_processing(
        self,
        trusted_identifier: LinkedExternalIdentifier,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        When two pre-existing references share a trusted identifier and both
        have pending duplicate decisions, running shortcut deduplication both
        references should result in a candidate and a duplicate.

        This can sometimes happen if we end up with duplicate delivery of our
        ingest reference tasks.
        """
        ref_1: Reference = ReferenceFactory.build(identifiers=[trusted_identifier])
        ref_2: Reference = ReferenceFactory.build(identifiers=[trusted_identifier])

        references = fake_repository([ref_1, ref_2])

        decision_1 = ReferenceDuplicateDecision(
            reference_id=ref_1.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )
        decision_2 = ReferenceDuplicateDecision(
            reference_id=ref_2.id,
            duplicate_determination=DuplicateDetermination.PENDING,
        )

        reference_duplicate_decisions = fake_repository([decision_1, decision_2])

        link_fake_repos(
            reference_duplicate_decisions,
            references,
            fk="reference_id",
            attr="duplicate_decision",
            filter_field="active_decision",
            filter_value=True,
        )

        uow = fake_uow(
            references=references,
            reference_duplicate_decisions=reference_duplicate_decisions,
        )
        uow.references.find_with_identifiers = AsyncMock(return_value=[ref_1, ref_2])

        service = DeduplicationService(
            anti_corruption_service,
            sql_uow=uow,
            es_uow=fake_uow(),
        )

        results_decision_1 = await service.shortcut_deduplication_using_identifiers(
            decision_1,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )

        assert results_decision_1
        assert len(results_decision_1) == 2

        assert results_decision_1[0].reference_id == ref_1.id
        assert (
            results_decision_1[0].duplicate_determination
            == DuplicateDetermination.CANONICAL
        )
        assert results_decision_1[0].detail == "Shortcutted with trusted identifier(s)"

        assert results_decision_1[1].reference_id == ref_2.id
        assert (
            results_decision_1[1].duplicate_determination
            == DuplicateDetermination.DUPLICATE
        )
        assert results_decision_1[1].canonical_reference_id == ref_1.id
        assert results_decision_1[1].detail == (
            f"Shortcutted via proxy reference {ref_1.id} " "with trusted identifier(s)"
        )

        results_decision_2 = await service.shortcut_deduplication_using_identifiers(
            decision_2,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )

        assert results_decision_2
        assert len(results_decision_2) == 1
        assert results_decision_2

        assert results_decision_2[0].reference_id == ref_2.id
        assert (
            results_decision_2[0].duplicate_determination
            == DuplicateDetermination.DUPLICATE
        )
        assert results_decision_2[0].canonical_reference_id == ref_1.id
        assert results_decision_2[0].detail == (
            "Shortcutted with trusted identifier(s)"
        )
