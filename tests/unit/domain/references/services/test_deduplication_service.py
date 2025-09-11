import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from destiny_sdk.identifiers import DOIIdentifier, OtherIdentifier

from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import (
    DuplicateDetermination,
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
async def test_detect_duplicates_happy_path(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    candidate_id = uuid.uuid4()
    decision = ReferenceDuplicateDecision(
        reference_id=reference_with_identifiers.id,
        candidate_duplicate_ids=[candidate_id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )
    sql_uow.reference_duplicate_decisions.update_by_pk.return_value = decision
    result = await service.detect_duplicates(decision)
    assert result == decision


@pytest.mark.asyncio
async def test_detect_duplicates_invalid_state(
    reference_with_identifiers, anti_corruption_service, sql_uow, es_uow
):
    service = DeduplicationService(anti_corruption_service, sql_uow, es_uow)
    decision = ReferenceDuplicateDecision(
        reference_id=reference_with_identifiers.id,
        candidate_duplicate_ids=[],
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    with pytest.raises(DeduplicationValueError):
        await service.detect_duplicates(decision)
