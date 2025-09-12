import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from destiny_sdk.identifiers import DOIIdentifier, OtherIdentifier

from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import (
    DuplicateDetermination,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceDuplicateDeterminationResult,
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
def anti_corruption_service():
    return MagicMock(spec=ReferenceAntiCorruptionService)


@pytest.fixture
def sql_uow():
    mock = MagicMock()
    mock.references.find_with_identifiers = AsyncMock()
    mock.reference_duplicate_decisions.add = AsyncMock()
    mock.reference_duplicate_decisions.update_by_pk = AsyncMock()
    mock.references.get_by_pk = AsyncMock()
    return mock


@pytest.fixture
def es_uow():
    mock = MagicMock()
    mock.references.search_for_candidate_duplicates = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_find_exact_duplicate_happy_path(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    candidate = MagicMock(spec=Reference)
    candidate.is_superset.return_value = True
    sql_uow.references.find_with_identifiers.return_value = [candidate]
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    result = await service.find_exact_duplicate(reference_with_identifiers)
    assert result == candidate


@pytest.mark.asyncio
async def test_find_exact_duplicate_no_identifiers(
    anti_corruption_service, sql_uow, es_uow
):
    ref = Reference(id=uuid.uuid4(), identifiers=None)
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    with pytest.raises(DeduplicationValueError):
        await service.find_exact_duplicate(ref)


@pytest.mark.asyncio
async def test_find_exact_duplicate_only_other_identifier(
    anti_corruption_service, sql_uow, es_uow
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
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    result = await service.find_exact_duplicate(ref)
    assert result is None


@pytest.mark.asyncio
async def test_register_duplicate_decision_for_reference_happy_path(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    decision = ReferenceDuplicateDecision(
        reference_id=reference_with_identifiers.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    sql_uow.reference_duplicate_decisions.add.return_value = decision
    result = await service.register_duplicate_decision_for_reference(
        reference_with_identifiers
    )
    assert result == decision


@pytest.mark.asyncio
async def test_register_duplicate_decision_invalid_combination(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    with pytest.raises(DeduplicationValueError):
        await service.register_duplicate_decision_for_reference(
            reference_with_identifiers,
            duplicate_determination=DuplicateDetermination.EXACT_DUPLICATE,
            canonical_reference_id=None,
        )


@pytest.mark.asyncio
async def test_nominate_candidate_duplicates_candidates_found(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    decision = ReferenceDuplicateDecision(
        reference_id=reference_with_identifiers.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    candidate_result = [MagicMock(id=uuid.uuid4())]
    es_uow.references.search_for_candidate_duplicates.return_value = candidate_result
    sql_uow.references.get_by_pk.return_value = reference_with_identifiers
    sql_uow.reference_duplicate_decisions.update_by_pk.return_value = decision
    result = await service.nominate_candidate_duplicates(decision)
    assert result == decision
    es_uow.references.search_for_candidate_duplicates.assert_awaited()


@pytest.mark.asyncio
async def test_nominate_candidate_duplicates_no_candidates(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    decision = ReferenceDuplicateDecision(
        reference_id=reference_with_identifiers.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    es_uow.references.search_for_candidate_duplicates.return_value = []
    sql_uow.references.get_by_pk.return_value = reference_with_identifiers
    sql_uow.reference_duplicate_decisions.update_by_pk.return_value = decision
    result = await service.nominate_candidate_duplicates(decision)
    assert result == decision
    es_uow.references.search_for_candidate_duplicates.assert_awaited()


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_happy_path(
    sql_uow, anti_corruption_service, es_uow
):
    # Setup reference and decision
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    reference.duplicate_decision = None

    candidate_id = uuid.uuid4()
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_duplicate_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )

    # Patch __placeholder_duplicate_determinator to return DUPLICATE
    result_obj = ReferenceDuplicateDeterminationResult(
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=candidate_id,
        detail="duplicate found",
    )

    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    with patch.object(
        service,
        "_DeduplicationService__placeholder_duplicate_determinator",
        return_value=result_obj,
    ) as mock_determine:
        sql_uow.references.get_by_pk.return_value = reference
        sql_uow.reference_duplicate_decisions.merge = AsyncMock(return_value=decision)
        out_decision = await service.determine_and_map_duplicate(decision)
        assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
        assert out_decision.canonical_reference_id == candidate_id
        assert out_decision.detail == "duplicate found"
        mock_determine.assert_called_once_with(decision)
        sql_uow.reference_duplicate_decisions.merge.assert_awaited()


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_invalid_input_raises(
    sql_uow, anti_corruption_service, es_uow
):
    reference = MagicMock(spec=Reference)
    reference.id = uuid.uuid4()
    reference.duplicate_decision = None

    # Case 1: No candidate_duplicate_ids
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_duplicate_ids=[],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    sql_uow.references.get_by_pk.return_value = reference
    with pytest.raises(DeduplicationValueError):
        await service.determine_and_map_duplicate(decision)

    # Case 2: Wrong determination state
    candidate_id = uuid.uuid4()
    decision2 = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_duplicate_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    with pytest.raises(DeduplicationValueError):
        await service.determine_and_map_duplicate(decision2)


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_canonical_change(
    sql_uow, anti_corruption_service, es_uow
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

    candidate_id = uuid.uuid4()
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_duplicate_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )

    result_obj = ReferenceDuplicateDeterminationResult(
        duplicate_determination=DuplicateDetermination.CANONICAL,
        canonical_reference_id=None,
        detail="now canonical",
    )

    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    with patch.object(
        service,
        "_DeduplicationService__placeholder_duplicate_determinator",
        return_value=result_obj,
    ):
        sql_uow.references.get_by_pk.return_value = reference
        sql_uow.reference_duplicate_decisions.merge = AsyncMock(return_value=decision)
        out_decision = await service.determine_and_map_duplicate(decision)
        assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
        assert (
            "Decouple reason: Existing duplicate decision changed."
            in out_decision.detail
        )
        sql_uow.reference_duplicate_decisions.merge.assert_awaited()


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_different_canonical(
    sql_uow, anti_corruption_service, es_uow
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
        candidate_duplicate_ids=[canonical_b],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )

    result_obj = ReferenceDuplicateDeterminationResult(
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_b,
        detail="different canonical",
    )

    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    with patch.object(
        service,
        "_DeduplicationService__placeholder_duplicate_determinator",
        return_value=result_obj,
    ):
        sql_uow.references.get_by_pk.return_value = reference
        sql_uow.reference_duplicate_decisions.merge = AsyncMock(return_value=decision)
        out_decision = await service.determine_and_map_duplicate(decision)
        assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
        assert (
            "Decouple reason: Existing duplicate decision changed."
            in out_decision.detail
        )
        sql_uow.reference_duplicate_decisions.merge.assert_awaited()


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_chain_length(
    sql_uow, anti_corruption_service, es_uow
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
        candidate_duplicate_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )

    result_obj = ReferenceDuplicateDeterminationResult(
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=candidate_id,
        detail="chain length reached",
    )

    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    # Patch settings.max_reference_duplicate_depth to 2
    service.__class__.settings = MagicMock(max_reference_duplicate_depth=2)
    with patch.object(
        service,
        "_DeduplicationService__placeholder_duplicate_determinator",
        return_value=result_obj,
    ):
        sql_uow.references.get_by_pk.return_value = reference
        sql_uow.reference_duplicate_decisions.merge = AsyncMock(return_value=decision)
        out_decision = await service.determine_and_map_duplicate(decision)
        assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
        assert (
            "Decouple reason: Max duplicate chain length reached."
            in out_decision.detail
        )
        sql_uow.reference_duplicate_decisions.merge.assert_awaited()
