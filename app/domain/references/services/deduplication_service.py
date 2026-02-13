"""Service for managing reference duplicate detection."""

from typing import Literal
from uuid import UUID

from opentelemetry import trace

from app.core.config import Environment, get_settings
from app.core.constants import MAX_REFERENCE_DUPLICATE_DEPTH
from app.core.exceptions import DeduplicationValueError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    DuplicateDetermination,
    ExternalIdentifierType,
    GenericExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceDuplicateDeterminationResult,
)
from app.domain.references.models.projections import (
    ReferenceSearchFieldsProjection,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class DeduplicationService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing reference duplicate detection."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    async def find_exact_duplicate(self, reference: Reference) -> Reference | None:
        """
        Find exact duplicate references for the given reference.

        This is *not* part of the regular deduplication flow but is used to circumvent
        importing and processing redundant references.

        Exact duplicates are defined in
        :attr:`app.domain.references.models.models.Reference.is_superset()`.
        A reference may have more than one exact duplicate, this just returns the first.

        :param reference: The reference to find duplicates for.
        :type reference: app.domain.references.models.models.Reference
        :return: The supersetting reference, or None if no duplicate was found.
        :rtype: app.domain.references.models.models.Reference | None
        """
        if not reference.identifiers:
            msg = "Reference must have identifiers to find duplicates."
            raise DeduplicationValueError(msg)

        # We can't be sure of low cardinality on "other" identifiers, so make sure
        # there's at least one defined identifier type.
        if not any(
            identifier.identifier.identifier_type != ExternalIdentifierType.OTHER
            for identifier in reference.identifiers
        ):
            logger.warning(
                "Reference did not have any non-other identifiers, exact duplicate "
                "search skipped."
            )
            return None

        # First, find candidates. These are the references with all identical
        # identifiers to the given reference.
        candidates = await self.sql_uow.references.find_with_identifiers(
            [
                GenericExternalIdentifier.from_specific(identifier.identifier)
                for identifier in reference.identifiers
            ],
            preload=["identifiers", "enhancements", "duplicate_decision"],
        )

        # Now, find if any candidates are perfect supersets of the new reference.
        # Try canonical references first to form a nicer tree, but it's
        # not super important.
        for candidate in sorted(
            candidates,
            key=lambda candidate: (
                1
                if candidate.is_canonical is True
                else 0
                if candidate.is_canonical is False
                else -1
            ),
            reverse=True,
        ):
            if candidate.is_superset(reference):
                return candidate
        return None

    async def register_duplicate_decision_for_reference(
        self,
        reference_id: UUID,
        enhancement_id: UUID | None = None,
        duplicate_determination: Literal[DuplicateDetermination.EXACT_DUPLICATE]
        | None = None,
        canonical_reference_id: UUID | None = None,
    ) -> ReferenceDuplicateDecision:
        """
        Register a duplicate decision for a reference.

        :param reference: The reference to register the duplicate decision for.
        :type reference: app.domain.references.models.models.Reference
        :param enhancement_id: The enhancement ID triggering with the duplicate
            decision, defaults to None
        :type enhancement_id: UUID | None, optional
        :param duplicate_determination: Flag indicating if a reference was an exact
            duplicate and not imported, defaults to None
        :type duplicate_determination: Literal[DuplicateDetermination.EXACT_DUPLICATE]
            | None, optional
        :param canonical_reference_id: The canonical reference ID this reference is an
            exact duplicate of, defaults to None
        :type canonical_reference_id: UUID | None, optional
        :return: The registered duplicate decision
        :rtype: ReferenceDuplicateDecision
        """
        if (duplicate_determination is not None) != (
            canonical_reference_id is not None
        ):
            msg = (
                "Both or neither of duplicate_determination and "
                "canonical_reference_id must be provided."
            )
            raise DeduplicationValueError(msg)
        _duplicate_determination = (
            duplicate_determination
            if duplicate_determination
            else DuplicateDetermination.PENDING
        )
        reference_duplicate_decision = ReferenceDuplicateDecision(
            reference_id=reference_id,
            enhancement_id=enhancement_id,
            duplicate_determination=_duplicate_determination,
            canonical_reference_id=canonical_reference_id,
            # If exact duplicate passed in, the decision is terminal and hence active
            active_decision=_duplicate_determination
            == DuplicateDetermination.EXACT_DUPLICATE,
        )
        return await self.sql_uow.reference_duplicate_decisions.add(
            reference_duplicate_decision
        )

    async def nominate_candidate_canonicals(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDecision:
        """
        Nominate candidate canonical references for the given decision.

        This uses the search strategy in
        :attr:`app.domain.references.repository.ReferenceESRepository.search_for_candidate_canonicals`.

        :param reference_duplicate_decision: The decision to find candidates for.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The updated decision with candidate IDs and status.
        :rtype: ReferenceDuplicateDecision
        """
        reference = await self.sql_uow.references.get_by_pk(
            reference_duplicate_decision.reference_id,
            preload=["enhancements", "identifiers"],
        )

        search_fields = (
            ReferenceSearchFieldsProjection.get_canonical_candidate_search_fields(
                reference
            )
        )

        if not search_fields.is_searchable:
            return await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                reference_duplicate_decision.id,
                duplicate_determination=DuplicateDetermination.UNSEARCHABLE,
            )
        search_result = await self.es_uow.references.search_for_candidate_canonicals(
            search_fields,
            reference_id=reference.id,
            scoring_config=settings.dedup_scoring,
        )

        if not search_result:
            reference_duplicate_decision = (
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    # This should simplify to CANONICAL only once the search strategy is
                    # implemented and evaluated.
                    duplicate_determination=DuplicateDetermination.CANONICAL
                    if settings.env == Environment.TEST
                    else DuplicateDetermination.UNSEARCHABLE,
                )
            )
        else:
            # Is there a search result score that would be enough for us to mark as
            # duplicate without proceeding to the next step?
            reference_duplicate_decision = (
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    candidate_canonical_ids=[result.id for result in search_result],
                    duplicate_determination=DuplicateDetermination.NOMINATED,
                )
            )

        return reference_duplicate_decision

    async def __placeholder_duplicate_determinator(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDeterminationResult:
        """
        Implement a basic placeholder duplicate determinator.

        Temporary implementation: takes the first candidate as the duplicate.
        This is the one with the highest score in the candidate nomination stage.
        This completes the flow but should not be used in production.

        :param reference_duplicate_decision: The decision to determine duplicates for.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The result of the duplicate determination.
        :rtype: ReferenceDuplicateDeterminationResult
        """
        return (
            ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.DUPLICATE,
                canonical_reference_id=reference_duplicate_decision.candidate_canonical_ids[
                    0
                ],
            )
            if settings.env == Environment.TEST
            and reference_duplicate_decision.candidate_canonical_ids
            else ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.UNSEARCHABLE,
                detail="Placeholder duplicate determinator used.",
            )
        )

    async def determine_canonical_from_candidates(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDecision:
        """
        Determine a canonical reference from its candidates.

        :param reference_duplicate_decision: The decision to determine duplicates for.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The updated decision with the determination result.
        :rtype: ReferenceDuplicateDecision
        """
        if (
            reference_duplicate_decision.duplicate_determination
            in DuplicateDetermination.get_terminal_states()
        ):
            return reference_duplicate_decision

        duplicate_determination_result = (
            await self.__placeholder_duplicate_determinator(
                reference_duplicate_decision
            )
        )

        return await self.sql_uow.reference_duplicate_decisions.update_by_pk(
            reference_duplicate_decision.id,
            detail=duplicate_determination_result.detail,
            duplicate_determination=duplicate_determination_result.duplicate_determination,
            canonical_reference_id=duplicate_determination_result.canonical_reference_id,
        )

    async def map_duplicate_decision(
        self, new_decision: ReferenceDuplicateDecision
    ) -> tuple[ReferenceDuplicateDecision, bool]:
        """
        Apply the persistence changes from the new duplicate decision.

        If the new decision is not terminal, it is not made active.

        :param new_decision: The new decision to apply.
        :type new_decision: ReferenceDuplicateDecision
        :return: The applied decision and whether it changed.
        :rtype: tuple[ReferenceDuplicateDecision, bool]
        """
        if (
            new_decision.duplicate_determination
            not in DuplicateDetermination.get_terminal_states()
        ):
            msg = "Only terminal duplicate determinations can be mapped."
            raise DeduplicationValueError(msg)

        reference = await self.sql_uow.references.get_by_pk(
            new_decision.reference_id,
            preload=["duplicate_decision", "canonical_reference"],
        )
        active_decision = reference.duplicate_decision

        # Preset to True, will be flipped if not changed
        decision_changed = True

        # Remap active decision if needed and handle other cases
        if new_decision.duplicate_determination == DuplicateDetermination.UNSEARCHABLE:
            new_decision.active_decision = True
            if active_decision:
                active_decision.active_decision = False
        elif active_decision and (
            (
                # Reference was duplicate but is now canonical
                new_decision.duplicate_determination == DuplicateDetermination.CANONICAL
                and active_decision.duplicate_determination
                == DuplicateDetermination.DUPLICATE
            )
            or (
                # Reference was duplicate but is now duplicate of a different canonical
                new_decision.duplicate_determination
                == active_decision.duplicate_determination
                == DuplicateDetermination.DUPLICATE
                and active_decision.canonical_reference_id
                != new_decision.canonical_reference_id
            )
        ):
            # Maintain existing decision and raise for manual review
            new_decision.duplicate_determination = DuplicateDetermination.DECOUPLED
            new_decision.detail = (
                "Decouple reason: Existing duplicate decision changed. "
                + (new_decision.detail if new_decision.detail else "")
            )
        elif (
            # Reference forms a chain longer than allowed
            new_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
            and reference.canonical_chain_length == MAX_REFERENCE_DUPLICATE_DEPTH
        ):
            # Raise for manual review
            new_decision.duplicate_determination = DuplicateDetermination.DECOUPLED
            new_decision.detail = (
                "Decouple reason: Max duplicate chain length reached. "
                + (new_decision.detail if new_decision.detail else "")
            )
        else:
            # Either:
            # - No active decision
            # - Decision is the same
            # - Decision is moving from canonical to duplicate
            # Just update the active decision to record the consistent state.
            if active_decision:
                if (
                    active_decision.duplicate_determination
                    == new_decision.duplicate_determination
                ):
                    decision_changed = False
                active_decision.active_decision = False
            new_decision.active_decision = True

        # Update in-place, it's just easier
        if active_decision:
            await self.sql_uow.reference_duplicate_decisions.merge(active_decision)
        new_decision = await self.sql_uow.reference_duplicate_decisions.merge(
            new_decision
        )

        return new_decision, decision_changed

    async def shortcut_deduplication_using_identifiers(  # noqa: PLR0912
        self,
        reference_duplicate_decision: ReferenceDuplicateDecision,
        trusted_unique_identifier_types: set[ExternalIdentifierType],
    ) -> list[ReferenceDuplicateDecision] | None:
        """
        Deduplicate the given reference using trusted unique identifiers.

        This shortcuts the regular deduplication flow and is only run on import.

        This is a very powerful operation and should only be used with identifier types
        that are certain to be unique and reliable. Misuse can lead to incorrect
        duplicate relationships that are hard to correct.

        The search will likely return multiple references ("candidates"),
        to be handled by:

        **Terminal Cases:**

        **A.** If they all belong to the same duplicate relationship graph, the given
        reference will be marked as duplicate of that graph's canonical reference.

        **B.** If they belong to more than one duplicate relationship graph, the given
        reference is marked as decoupled for manual review, as it indicates disconnected
        duplicate relationship graphs and undermines the assumption of the shortcut.

        **C.** If none of them belong to a duplicate relationship graph, the given
        reference becomes the canonical of a new duplicate relationship graph including
        all candidates.

        **D.** If some of them belong to a single duplicate relationship graph and some
        don't, the non-graph references are marked as duplicates of the canonical of
        the graph.


        **Non-terminal Cases:**

        **E.** Finally, if the given reference has no trusted identifiers or no
        candidates are found, no action is taken and regular deduplication continues.


        :param reference: The reference to deduplicate.
        :type reference: app.domain.references.models.models.Reference
        :param trusted_unique_identifier_types: The identifier types considered
            trusted unique identifiers.
        :type trusted_unique_identifier_types: set[ExternalIdentifierType]
        :return: The generated duplicate decisions, if any.
        :rtype: list[ReferenceDuplicateDecision] | None
        """
        if reference_duplicate_decision.duplicate_determination != (
            DuplicateDetermination.PENDING
        ):
            msg = "Shortcut deduplication can only be run on pending decisions."
            raise DeduplicationValueError(msg)

        reference = await self.sql_uow.references.get_by_pk(
            reference_duplicate_decision.reference_id,
            preload=["identifiers", "duplicate_decision"],
        )
        if not reference.identifiers or reference.duplicate_decision:
            # No identifiers or already deduplicated, skip shortcutting
            return None

        trusted_identifiers = [
            GenericExternalIdentifier.from_specific(identifier.identifier)
            for identifier in reference.identifiers
            if identifier.identifier.identifier_type in trusted_unique_identifier_types
        ]
        candidates = await self.sql_uow.references.find_with_identifiers(
            trusted_identifiers,
            preload=["duplicate_decision"],
            match="any",
        )
        candidates = [
            candidate for candidate in candidates if candidate.id != reference.id
        ]
        if not candidates:
            if not trusted_identifiers:
                # No trusted identifiers to shortcut with, fall through to ES
                return None
            # Has trusted identifiers but no existing matches - new unique reference
            # Skip ES deduplication entirely since the trusted identifier guarantees
            # uniqueness within its source (e.g., OpenAlex W-ID)
            reference_duplicate_decision.duplicate_determination = (
                DuplicateDetermination.CANONICAL
            )
            reference_duplicate_decision.detail = (
                "New reference with trusted identifier(s), no existing matches"
            )
            reference_duplicate_decision, _ = await self.map_duplicate_decision(
                reference_duplicate_decision
            )
            return [reference_duplicate_decision]

        canonical_ids, undeduplicated_ids = set(), set()
        for candidate in candidates:
            if (
                not candidate.duplicate_decision
                or candidate.duplicate_decision.duplicate_determination
                == DuplicateDetermination.UNSEARCHABLE
            ):
                undeduplicated_ids.add(candidate.id)
            elif candidate.is_canonical:
                canonical_ids.add(candidate.id)
            else:
                # Duplicate of a canonical, find the canonical ID
                # We get this fresh without the filters so we can traverse a chain if
                # required
                canonical_reference = await self.sql_uow.references.get_by_pk(
                    candidate.id, preload=["canonical_reference"]
                )
                while canonical_reference.canonical_reference:
                    canonical_reference = canonical_reference.canonical_reference
                canonical_ids.add(canonical_reference.id)

        if len(canonical_ids) > 1:
            return [
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    duplicate_determination=DuplicateDetermination.DECOUPLED,
                    detail=(
                        "Multiple canonical references found for trusted unique "
                        "identifiers. This may indicate we have disconnected duplicate "
                        "relationship graphs. Manual review required. Canonical IDs: "
                        f"{', '.join(
                            str(canonical_id) for canonical_id in canonical_ids
                        )}"
                    ),
                )
            ]

        if not canonical_ids:
            # No canonicals found, make this reference the canonical
            canonical_id = reference.id
            reference_duplicate_decision.duplicate_determination = (
                DuplicateDetermination.CANONICAL
            )
            reference_duplicate_decision.detail = (
                "Shortcutted with trusted identifier(s)"
            )

            reference_duplicate_decision, _ = await self.map_duplicate_decision(
                reference_duplicate_decision
            )
        else:
            # Exactly one canonical found, make this reference a duplicate of it
            canonical_id = canonical_ids.pop()
            reference_duplicate_decision.duplicate_determination = (
                DuplicateDetermination.DUPLICATE
            )
            reference_duplicate_decision.canonical_reference_id = canonical_id
            reference_duplicate_decision.detail = (
                "Shortcutted with trusted identifier(s)"
            )
            reference_duplicate_decision, _ = await self.map_duplicate_decision(
                reference_duplicate_decision
            )

        # Map any undeduplicated candidates as duplicates of the canonical
        side_effect_decisions = []
        for candidate_id in undeduplicated_ids:
            decision, _ = await self.map_duplicate_decision(
                ReferenceDuplicateDecision(
                    reference_id=candidate_id,
                    duplicate_determination=DuplicateDetermination.DUPLICATE,
                    canonical_reference_id=canonical_id,
                    active_decision=True,
                    detail=(
                        f"Shortcutted via proxy reference {reference.id} "
                        "with trusted identifier(s)"
                    ),
                )
            )
            side_effect_decisions.append(decision)

        return [reference_duplicate_decision, *side_effect_decisions]
