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
from app.domain.references.services.deduplication_service import (
    DeduplicationService,
    clean_doi,
)
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    RawEnhancementFactory,
    ReferenceFactory,
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
async def test_determine_scores_candidates_and_returns_determination(
    fake_uow, fake_repository, anti_corruption_service
):
    """Test that determine scores candidates using dedup_lab scorer."""
    from tests.factories import (
        BibliographicMetadataEnhancementFactory,
        EnhancementFactory,
        ReferenceFactory,
    )

    # Create source reference with enhancements (no identifiers)
    source_ref = ReferenceFactory.build(identifiers=[])
    source_ref.enhancements = [
        EnhancementFactory.build(
            reference_id=source_ref.id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="Climate change impacts on biodiversity",
                publication_year=2023,
            ),
        )
    ]
    source_ref.duplicate_decision = None

    # Create candidate reference with different title (should score LOW)
    candidate_ref = ReferenceFactory.build(identifiers=[])
    candidate_ref.enhancements = [
        EnhancementFactory.build(
            reference_id=candidate_ref.id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="Machine learning in healthcare applications",
                publication_year=2022,
            ),
        )
    ]

    decision = ReferenceDuplicateDecision(
        reference_id=source_ref.id,
        candidate_canonical_ids=[candidate_ref.id],
        candidate_canonical_scores={str(candidate_ref.id): 25.0},  # Low ES score
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )

    ref_repo = fake_repository([source_ref, candidate_ref])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )

    # With very different titles, should score low and return CANONICAL
    determined = await service.determine_canonical_from_candidates(decision)
    assert determined.duplicate_determination == DuplicateDetermination.CANONICAL
    assert determined.canonical_reference_id is None
    assert "Top scores:" in determined.detail


@pytest.mark.asyncio
async def test_determine_marks_duplicate_for_high_confidence_match(
    fake_uow, fake_repository, anti_corruption_service
):
    """Test that determine marks DUPLICATE for high-confidence matches."""
    from tests.factories import (
        BibliographicMetadataEnhancementFactory,
        DOIIdentifierFactory,
        EnhancementFactory,
        LinkedExternalIdentifierFactory,
        ReferenceFactory,
    )

    # Create source reference
    source_ref = ReferenceFactory.build()
    source_doi = DOIIdentifierFactory.build()
    source_ref.identifiers = [
        LinkedExternalIdentifierFactory.build(
            reference_id=source_ref.id,
            identifier=source_doi,
        )
    ]
    source_ref.enhancements = [
        EnhancementFactory.build(
            reference_id=source_ref.id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="Climate change impacts on biodiversity",
                publication_year=2023,
            ),
        )
    ]
    source_ref.duplicate_decision = None

    # Create candidate reference with SAME DOI (should score HIGH via identifier match)
    candidate_ref = ReferenceFactory.build()
    candidate_ref.identifiers = [
        LinkedExternalIdentifierFactory.build(
            reference_id=candidate_ref.id,
            identifier=source_doi,  # Same DOI = exact match
        )
    ]
    candidate_ref.enhancements = [
        EnhancementFactory.build(
            reference_id=candidate_ref.id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="Climate change impacts on biodiversity",
                publication_year=2023,
            ),
        )
    ]

    decision = ReferenceDuplicateDecision(
        reference_id=source_ref.id,
        candidate_canonical_ids=[candidate_ref.id],
        duplicate_determination=DuplicateDetermination.NOMINATED,
    )

    ref_repo = fake_repository([source_ref, candidate_ref])
    dec_repo = fake_repository([decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )

    # With same DOI and title, should score high and return DUPLICATE
    determined = await service.determine_canonical_from_candidates(decision)
    assert determined.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert determined.canonical_reference_id == candidate_ref.id
    assert "High confidence" in determined.detail


@pytest.mark.asyncio
async def test_map_duplicate_no_change_when_same_canonical(
    fake_uow, fake_repository, anti_corruption_service
):
    """Test that mapping DUPLICATE to same canonical doesn't change the decision."""
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    canonical_id = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_id,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    # Create a new decision that would map to the same canonical
    new_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_id,
    )

    ref_repo = fake_repository([reference])
    dec_repo = fake_repository([new_decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    # Directly test map_duplicate_decision with a terminal decision
    out_decision, decision_changed = await service.map_duplicate_decision(new_decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert out_decision.canonical_reference_id == canonical_id
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
async def test_map_duplicate_decoupled_when_canonical_changes(
    fake_uow, fake_repository, anti_corruption_service
):
    """Test decoupling when reference was DUPLICATE of A, now DUPLICATE of B."""
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    canonical_a = uuid7()
    canonical_b = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_a,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    # Create a new DUPLICATE decision with different canonical
    new_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=canonical_b,
    )

    ref_repo = fake_repository([reference])
    dec_repo = fake_repository([active_decision, new_decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    # Directly test map_duplicate_decision
    out_decision, decision_changed = await service.map_duplicate_decision(new_decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert (
        "Decouple reason: Existing duplicate decision changed." in out_decision.detail
    )
    assert decision_changed


@pytest.mark.asyncio
async def test_map_duplicate_decoupled_when_chain_too_long(
    fake_uow, fake_repository, anti_corruption_service
):
    """Test decoupling when duplicate chain exceeds max depth."""
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

    candidate_id = uuid7()
    decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=candidate_id,
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

    # Directly test map_duplicate_decision
    out_decision, decision_changed = await service.map_duplicate_decision(decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    assert "Decouple reason: Max duplicate chain length reached." in out_decision.detail
    assert decision_changed


@pytest.mark.asyncio
async def test_map_canonical_becomes_duplicate(
    fake_uow, fake_repository, anti_corruption_service
):
    """Test that a CANONICAL reference can become a DUPLICATE."""
    reference = MagicMock(spec=Reference)
    reference.id = uuid7()
    active_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
        canonical_reference_id=None,
        active_decision=True,
    )
    reference.duplicate_decision = active_decision

    candidate_id = uuid7()
    new_decision = ReferenceDuplicateDecision(
        reference_id=reference.id,
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        canonical_reference_id=candidate_id,
    )

    ref_repo = fake_repository([reference])
    dec_repo = fake_repository([active_decision, new_decision])
    service = DeduplicationService(
        anti_corruption_service,
        fake_uow(
            references=ref_repo,
            reference_duplicate_decisions=dec_repo,
        ),
        fake_uow(),
    )
    # Directly test map_duplicate_decision
    out_decision, decision_changed = await service.map_duplicate_decision(new_decision)
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    assert decision_changed
    old_decision = await dec_repo.get_by_pk(active_decision.id)
    assert not old_decision.active_decision
    out_decision = await dec_repo.get_by_pk(out_decision.id)
    assert out_decision.active_decision
    assert out_decision.duplicate_determination == DuplicateDetermination.DUPLICATE


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
        assert canonical.identifiers
        assert duplicate.identifiers
        # Both canonical and duplicate should have the trusted identifier
        # This reflects reality: find_with_identifiers only returns refs with matching IDs
        canonical.identifiers.append(trusted_identifier)
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

        # No trusted identifiers
        assert not await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types=set(),
        )

        # No matching references found with OpenAlex ID -> marks CANONICAL
        # (OpenAlex IDs are globally unique, so no match = new unique record)
        result = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types={ExternalIdentifierType.OPEN_ALEX},
        )
        assert result is not None
        assert len(result) == 1
        assert result[0].duplicate_determination == DuplicateDetermination.CANONICAL
        assert result[0].detail == "New OpenAlex record (W ID not in corpus)"

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

    async def test_shortcut_deduplication_conflicting_identifiers(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        fake_uow,
        fake_repository,
    ):
        """
        Test that conflicting trusted identifiers (same DOI, different OpenAlex IDs)
        result in UNRESOLVED status for manual review.

        This handles the case where malformed DOIs in source data (e.g., placeholder
        DOIs like "10.5007/%x") are shared across multiple distinct OpenAlex works.
        """
        from destiny_sdk.identifiers import DOIIdentifier

        from tests.factories import DOIIdentifierFactory

        # Create incoming reference with OpenAlex ID and a shared (bad) DOI
        shared_doi = DOIIdentifierFactory.build(identifier="10.5007/%x")
        incoming_openalex = OpenAlexIdentifierFactory.build(identifier="W1111111111")

        incoming: Reference = ReferenceFactory.build()
        assert incoming.identifiers is not None
        incoming.identifiers = [
            LinkedExternalIdentifierFactory.build(
                identifier=incoming_openalex,
                reference_id=incoming.id,
            ),
            LinkedExternalIdentifierFactory.build(
                identifier=shared_doi,
                reference_id=incoming.id,
            ),
        ]

        # Create existing reference with DIFFERENT OpenAlex ID but SAME DOI
        existing_openalex = OpenAlexIdentifierFactory.build(identifier="W2222222222")
        existing: Reference = ReferenceFactory.build()
        assert existing.identifiers is not None
        existing.identifiers = [
            LinkedExternalIdentifierFactory.build(
                identifier=existing_openalex,
                reference_id=existing.id,
            ),
            LinkedExternalIdentifierFactory.build(
                identifier=shared_doi,
                reference_id=existing.id,
            ),
        ]

        repo = fake_repository([incoming, existing])
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
        # Simulate finding the existing ref via DOI match
        uow.references.find_with_identifiers = AsyncMock(return_value=[existing])

        result = await service.shortcut_deduplication_using_identifiers(
            decision,
            trusted_unique_identifier_types={
                ExternalIdentifierType.OPEN_ALEX,
                ExternalIdentifierType.DOI,
            },
        )

        assert result is not None
        assert len(result) == 1
        assert result[0].duplicate_determination == DuplicateDetermination.UNRESOLVED
        assert "Conflicting trusted identifiers" in result[0].detail
        assert "W1111111111" in result[0].detail
        assert "W2222222222" in result[0].detail
        assert "10.5007/%x" in result[0].detail


class TestCleanDOI:
    """Test DOI cleanup function that detects and removes URL cruft."""

    def test_clean_doi_no_changes(self):
        """Test that a clean DOI is returned unchanged."""
        result = clean_doi("10.1234/example")
        assert result.cleaned == "10.1234/example"
        assert result.original == "10.1234/example"
        assert not result.was_modified
        assert result.actions == []

    def test_clean_doi_html_entities(self):
        """Test that HTML entities are unescaped."""
        result = clean_doi("10.1234/example&amp;test")
        assert result.cleaned == "10.1234/example&test"
        assert result.was_modified
        assert "unescape_html" in result.actions

    def test_clean_doi_query_params(self):
        """Test that query parameters are stripped."""
        result = clean_doi("10.1234/example?utm_source=twitter&utm_campaign=share")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_query_params" in result.actions

    def test_clean_doi_jsessionid(self):
        """Test that jsessionid is stripped."""
        result = clean_doi("10.1234/example;jsessionid=ABC123DEF456")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_jsessionid" in result.actions

    def test_clean_doi_magic_tracking(self):
        """Test that magic tracking parameters are stripped."""
        result = clean_doi("10.1234/example&magic=repec:abc:123")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_magic" in result.actions

    def test_clean_doi_prog_tracking(self):
        """Test that prog tracking parameters are stripped."""
        result = clean_doi("10.1234/example&prog=normal")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_prog" in result.actions

    def test_clean_doi_utm_tracking(self):
        """Test that utm tracking parameters are stripped."""
        result = clean_doi("10.1234/example&utm_source=email")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        # Action name is truncated due to pattern[1:-1] slicing: "&utm" -> "ut"
        assert "strip_ut" in result.actions

    def test_clean_doi_abstract_suffix(self):
        """Test that /abstract suffix is stripped."""
        result = clean_doi("10.1234/example/abstract")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_abstract" in result.actions

    def test_clean_doi_full_suffix(self):
        """Test that /full suffix is stripped."""
        result = clean_doi("10.1234/example/full")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_full" in result.actions

    def test_clean_doi_pdf_suffix(self):
        """Test that /pdf suffix is stripped."""
        result = clean_doi("10.1234/example/pdf")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_pdf" in result.actions

    def test_clean_doi_epdf_suffix(self):
        """Test that /epdf suffix is stripped."""
        result = clean_doi("10.1234/example/epdf")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_epdf" in result.actions

    def test_clean_doi_summary_suffix(self):
        """Test that /summary suffix is stripped."""
        result = clean_doi("10.1234/example/summary")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        assert "strip_summary" in result.actions

    def test_clean_doi_multiple_issues(self):
        """Test that multiple cleanup steps are applied in sequence."""
        result = clean_doi("10.1234/example&amp;test?utm_source=web&magic=repec/pdf")
        assert result.cleaned == "10.1234/example&test"
        assert result.was_modified
        assert "unescape_html" in result.actions
        assert "strip_query_params" in result.actions
        # After stripping query params, other issues are already gone

    def test_clean_doi_complex_real_world_example(self):
        """Test a complex real-world DOI with multiple cruft patterns."""
        result = clean_doi("10.1016/j.cell.2020.01.001;jsessionid=XYZ?via=ihub&magic=test")
        assert result.cleaned == "10.1016/j.cell.2020.01.001"
        assert result.was_modified
        assert "strip_jsessionid" in result.actions
        assert "strip_query_params" in result.actions

    def test_clean_doi_whitespace_stripped(self):
        """Test that leading/trailing whitespace is stripped."""
        result = clean_doi("  10.1234/example  ")
        assert result.cleaned == "10.1234/example"
        assert result.was_modified
        # Whitespace stripping doesn't add to actions list, but was_modified is True

    def test_clean_doi_suffix_not_a_false_positive(self):
        """Test that DOI suffixes that are part of the DOI are not stripped."""
        # A DOI ending in "/full" that's actually part of the DOI itself
        # should not be stripped. However, our current implementation is conservative
        # and strips these suffixes. This test documents current behavior.
        result = clean_doi("10.1234/journal.full")
        # Current behavior: does NOT strip because "journal.full" doesn't end with "/full"
        assert result.cleaned == "10.1234/journal.full"
        assert not result.was_modified

    def test_clean_doi_preserves_valid_ampersand(self):
        """Test that valid ampersands in DOIs are preserved after unescaping."""
        result = clean_doi("10.1234/example&test")
        # No HTML entities, ampersand is valid DOI character
        assert result.cleaned == "10.1234/example&test"
        assert not result.was_modified

    @pytest.mark.parametrize(
        "dirty_doi,expected_clean",
        [
            # Real-world examples from overnight analysis
            ("10.1234/test?journalcode=abc", "10.1234/test"),
            ("10.1234/test&magic=repec:def:456", "10.1234/test"),
            ("10.1234/test;jsessionid=ABC123", "10.1234/test"),
            ("10.1234/test/abstract", "10.1234/test"),
            ("10.1234/test&amp;other", "10.1234/test&other"),
        ],
    )
    def test_clean_doi_parametrized_examples(self, dirty_doi: str, expected_clean: str):
        """Test parametrized real-world examples."""
        result = clean_doi(dirty_doi)
        assert result.cleaned == expected_clean
        assert result.was_modified
