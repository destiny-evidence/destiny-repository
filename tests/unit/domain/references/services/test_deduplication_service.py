import datetime
import itertools
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from destiny_sdk.enhancements import Authorship
from destiny_sdk.identifiers import OtherIdentifier

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
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    RawEnhancementFactory,
    ReferenceFactory,
)
from tests.unit.domain.conftest import link_fake_repos


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
async def test_register_duplicate_decision_for_reference_happy_path(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository()),
        fake_uow(),
    )
    result = await service.register_duplicate_decision_for_reference(reference.id)
    assert result.reference_id == reference.id
    assert result.duplicate_determination == DuplicateDetermination.PENDING


@pytest.mark.asyncio
async def test_register_duplicate_decision_invalid_combination(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(reference_duplicate_decisions=fake_repository()),
        fake_uow(),
    )
    with pytest.raises(DeduplicationValueError):
        await service.register_duplicate_decision_for_reference(
            reference.id,
            duplicate_determination=DuplicateDetermination.EXACT_DUPLICATE,
            canonical_reference_id=None,
        )


@pytest.mark.asyncio
async def test_nominate_candidate_canonicals_candidates_not_found(
    reference, anti_corruption_service, fake_uow, fake_repository
):
    reference.enhancements = []
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            reference_duplicate_decisions=fake_repository([decision]),
            references=fake_repository([reference]),
        ),
        fake_uow(),
    )

    # Patch service.es_uow to mock search_for_candidate_canonicals
    service.es_uow = MagicMock()
    candidate_result = [MagicMock(id=uuid7())]
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
    candidate_result = [MagicMock(id=uuid7())]
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
    reference.id = uuid7()
    reference.duplicate_decision = None

    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[canonical.id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    # Split: determine then map
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == canonical.id
    assert decision_changed
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_no_change(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and decision
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical.id,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[canonical.id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    # Split: determine then map
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == canonical.id
    assert decision_changed is False
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


@pytest.mark.asyncio
async def test_determine_no_op_terminal(
    fake_uow, fake_repository, anti_corruption_service
):
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
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
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
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
async def test_determine_and_map_duplicate_decoupled_different_canonical(
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
        candidate_canonical_ids=[canonical_b.id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_decoupled_chain_length(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference with canonical chain length 2 using real Reference objects
    canonical_reference = Reference(
        id=uuid7(),
        identifiers=[],
        enhancements=[],
        duplicate_decision=None,
        canonical_reference=None,
    )

    reference = Reference(
        id=uuid7(),
        identifiers=[],
        enhancements=[],
        duplicate_decision=None,
        canonical_reference=canonical_reference,
    )

    candidate = MagicMock(spec=Reference)
    candidate.id = uuid7()
    candidate.is_canonical = True

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[candidate.id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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

    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert "Decouple reason: Max duplicate chain length reached." in out_decision.detail
    assert decision_changed


@pytest.mark.asyncio
async def test_determine_and_map_duplicate_now_duplicate(
    fake_uow, fake_repository, anti_corruption_service
):
    # Setup reference and active decision (was CANONICAL, now DUPLICATE)
    canonical = MagicMock(spec=Reference)
    canonical.id = uuid7()
    canonical.is_canonical = True

    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        canonical_reference_id=None,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        candidate_canonical_ids=[canonical.id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
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
    determined = await service.determine_canonical_from_candidates(decision)
    out_decision, decision_changed = await service.map_duplicate_decision(determined)
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
