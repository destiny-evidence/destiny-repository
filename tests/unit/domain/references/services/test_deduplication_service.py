import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from destiny_sdk.enhancements import Authorship, BibliographicMetadataEnhancement
from destiny_sdk.identifiers import DOIIdentifier, OtherIdentifier

from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.deduplication_service import DeduplicationService


@pytest.fixture
def reference_with_identifiers():
    return Reference(
        id=uuid.uuid4(),
        identifiers=[
            LinkedExternalIdentifier(
                identifier=DOIIdentifier(
                    identifier="10.1000/xyz123",
                    identifier_type=ExternalIdentifierType.DOI,
                ),
                reference_id=uuid.uuid4(),
            )
        ],
    )


@pytest.fixture
def searchable_reference(reference_with_identifiers):
    return reference_with_identifiers.copy(
        update={
            "enhancements": [
                Enhancement(
                    source="test",
                    visibility="public",
                    content=BibliographicMetadataEnhancement(
                        authorship=[
                            Authorship(display_name="John Doe", position="first")
                        ],
                        publication_year=2025,
                        title="Maybe a duplicate reference, maybe not",
                    ),
                    reference_id=reference_with_identifiers.id,
                )
            ]
        }
    )


@pytest.fixture
def anti_corruption_service():
    return MagicMock(spec=ReferenceAntiCorruptionService)


@pytest.mark.asyncio
async def test_find_exact_duplicate_happy_path(
    reference_with_identifiers, anti_corruption_service, fake_uow, fake_repository
):
    candidate = reference_with_identifiers.copy(update={"id": uuid.uuid4()})
    repo = fake_repository([candidate])
    uow = fake_uow(references=repo)
    uow.references.find_with_identifiers = AsyncMock(return_value=[candidate])
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())
    result = await service.find_exact_duplicate(reference_with_identifiers)
    assert result == candidate
    # No longer a subset
    result = await service.find_exact_duplicate(
        reference_with_identifiers.copy(update={"visibility": "hidden"})
    )
    assert not result


@pytest.mark.asyncio
async def test_find_exact_duplicate_no_identifiers(
    anti_corruption_service, fake_uow, fake_repository
):
    ref = Reference(id=uuid.uuid4(), identifiers=None)
    uow = fake_uow(references=fake_repository())
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())
    with pytest.raises(DeduplicationValueError):
        await service.find_exact_duplicate(ref)


@pytest.mark.asyncio
async def test_find_exact_duplicate_only_other_identifier(
    anti_corruption_service, fake_uow, fake_repository
):
    ref = Reference(
        id=uuid.uuid4(),
        identifiers=[
            LinkedExternalIdentifier(
                identifier=OtherIdentifier(
                    identifier="otherid",
                    identifier_type=ExternalIdentifierType.OTHER,
                    other_identifier_name="other_name",
                ),
                reference_id=uuid.uuid4(),
            )
        ],
    )
    uow = fake_uow(references=fake_repository())
    service = DeduplicationService(anti_corruption_service, uow, fake_uow())
    result = await service.find_exact_duplicate(ref)
    assert result is None


@pytest.mark.asyncio
async def test_register_duplicate_decision_for_reference_happy_path(
    reference_with_identifiers, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository()),
        fake_uow(),
    )
    result = await service.register_duplicate_decision_for_reference(
        reference_with_identifiers
    )
    assert result.reference_id == reference_with_identifiers.id
    assert result.duplicate_determination == DuplicateDetermination.PENDING


@pytest.mark.asyncio
async def test_register_duplicate_decision_invalid_combination(
    reference_with_identifiers, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository()),
        fake_uow(),
    )
    with pytest.raises(DeduplicationValueError):
        await service.register_duplicate_decision_for_reference(
            reference_with_identifiers,
            duplicate_determination=DuplicateDetermination.EXACT_DUPLICATE,
            canonical_reference_id=None,
        )


@pytest.mark.asyncio
async def test_nominate_candidate_canonicals_candidates_not_found(
    reference_with_identifiers, anti_corruption_service, fake_uow, fake_repository
):
    decision = ReferenceDuplicateDecision(
        reference_id=reference_with_identifiers.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            reference_duplicate_decisions=fake_repository([decision]),
            references=fake_repository([reference_with_identifiers]),
        ),
        fake_uow(),
    )

    # Patch service.es_uow to mock search_for_candidate_canonicals
    service.es_uow = MagicMock()
    candidate_result = [MagicMock(id=uuid.uuid4())]
    service.es_uow.references.search_for_candidate_canonicals = AsyncMock(
        return_value=candidate_result
    )
    result = await service.nominate_candidate_canonicals(decision)
    assert result.duplicate_determination == DuplicateDetermination.UNSEARCHABLE
    assert not result.candidate_canonical_ids
    service.es_uow.references.search_for_candidate_canonicals.assert_not_awaited()


@pytest.mark.asyncio
async def test_nominate_candidate_canonicals_candidates_found(
    searchable_reference, anti_corruption_service, fake_uow, fake_repository
):
    decision = ReferenceDuplicateDecision(
        reference_id=searchable_reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            reference_duplicate_decisions=fake_repository([decision]),
            references=fake_repository([searchable_reference]),
        ),
        fake_uow(),
    )

    # Patch service.es_uow to mock search_for_candidate_duplicates
    service.es_uow = MagicMock()
    candidate_result = [MagicMock(id=uuid.uuid4())]
    service.es_uow.references.search_for_candidate_canonicals = AsyncMock(
        return_value=candidate_result
    )
    result = await service.nominate_candidate_canonicals(decision)
    assert result.duplicate_determination == DuplicateDetermination.NOMINATED
    assert result.candidate_canonical_ids == [candidate_result[0].id]
    service.es_uow.references.search_for_candidate_canonicals.assert_awaited()


@pytest.mark.asyncio
async def test_nominate_candidate_canonicals_no_candidates(
    searchable_reference, anti_corruption_service, fake_uow, fake_repository
):
    decision = ReferenceDuplicateDecision(
        reference_id=searchable_reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=fake_repository([searchable_reference]),
            reference_duplicate_decisions=fake_repository([decision]),
        ),
        fake_uow(),
    )
    # Patch service.es_uow to mock search_for_candidate_canonicals
    service.es_uow = MagicMock()
    service.es_uow.references.search_for_candidate_canonicals = AsyncMock(
        return_value=[]
    )
    result = await service.nominate_candidate_canonicals(decision)
    assert result.duplicate_determination == DuplicateDetermination.CANONICAL
    assert not result.candidate_canonical_ids
    service.es_uow.references.search_for_candidate_canonicals.assert_awaited()


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_happy_path(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and decision
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    reference.duplicate_decision = None

    candidate_id = uuid.uuid4()
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    # Split: determine then map
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == candidate_id
    assert decision_changed is True
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_no_change(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and decision
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=uuid.uuid4(),
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[active_decision.canonical_reference_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    # Split: determine then map
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == active_decision.canonical_reference_id
    assert decision_changed is False
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
async def test_determine_no_op_terminal(
    fake_uow, fake_repository, anti_corruption_service
):
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    reference.duplicate_decision = None

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[],
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
    determined = await service.determine_canonical_from_candidates(decision)
    assert determined == decision


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_canonical_change(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was DUPLICATE, now CANONICAL)
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=uuid.uuid4(),
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
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed is True
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert not out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_different_canonical(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was DUPLICATE of A, now DUPLICATE of B)
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    canonical_a = uuid.uuid4()
    canonical_b = uuid.uuid4()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_a,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[canonical_b],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed is True


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_chain_length(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference with canonical chain length 2 using real Reference objects
    canonical_reference = Reference(
        id=uuid.uuid4(),
        identifiers=[],
        enhancements=[],
        duplicate_decision=None,
        canonical_reference=None,
    )

    reference = Reference(
        id=uuid.uuid4(),
        identifiers=[],
        enhancements=[],
        duplicate_decision=None,
        canonical_reference=canonical_reference,
    )

    candidate_id = uuid.uuid4()
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    )  # Patch settings.max_reference_duplicate_depth to 2
    service.__class__.settings = MagicMock(max_reference_duplicate_depth=2)

    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert "Decouple reason: Max duplicate chain length reached." in out_decision.detail
    assert decision_changed is True


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_now_duplicate(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was CANONICAL, now DUPLICATE)
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        canonical_reference_id=None,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    candidate_id = uuid.uuid4()
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed is True
    old_decision = await dec_repo.get_by_pk(active_decision.id)
    assert old_decision.active_decision
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert not out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
