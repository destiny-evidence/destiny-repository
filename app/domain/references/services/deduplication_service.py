"""Service for managing reference duplicate detection."""

import html
import uuid
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from opentelemetry import trace

from app.core.config import get_settings
from app.core.constants import MAX_REFERENCE_DUPLICATE_DEPTH
from app.core.exceptions import DeduplicationValueError
from app.core.telemetry.logger import get_logger
from app.domain.references.deduplication.scoring import (
    ConfidenceLevel,
    PairScorer,
    ReferenceDeduplicationView,
)
from app.domain.references.models.models import (
    DuplicateDetermination,
    ExternalIdentifierType,
    GenericExternalIdentifier,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceDuplicateDeterminationResult,
)
from app.domain.references.models.projections import ReferenceSearchFieldsProjection
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


def _create_scorer() -> PairScorer:
    """Create a PairScorer configured from application settings."""
    # DedupScoringConfig satisfies ScoringConfigProtocol via property aliases
    return PairScorer(settings.dedup_scoring)


@dataclass
class DOICleanupResult:
    """Result of DOI cleanup attempt."""

    original: str
    cleaned: str
    was_modified: bool
    actions: list[str]


def clean_doi(doi: str) -> DOICleanupResult:
    """
    Clean a DOI by removing URL cruft.

    Returns the cleaned DOI and metadata about what was changed.
    This does NOT modify the stored DOI - it's used to detect if a DOI
    needs validation before being trusted.

    Handles:
    - HTML entity encoding (&amp; -> &)
    - Query parameters (?utm=..., ?journalcode=...)
    - Session IDs (;jsessionid=...)
    - Tracking garbage (&magic=repec..., &prog=normal)
    - URL path suffixes (/abstract, /full, /pdf)
    """
    actions: list[str] = []
    cleaned = doi

    # Step 1: Unescape HTML entities (&amp; -> &, etc.)
    if "&" in cleaned:
        unescaped = html.unescape(cleaned)
        if unescaped != cleaned:
            actions.append("unescape_html")
            cleaned = unescaped

    # Step 2: Strip query parameters
    if "?" in cleaned:
        actions.append("strip_query_params")
        cleaned = cleaned.split("?")[0]

    # Step 3: Strip session IDs
    if ";jsessionid=" in cleaned:
        actions.append("strip_jsessionid")
        cleaned = cleaned.split(";jsessionid=")[0]

    # Step 4: Strip tracking garbage after & (common patterns)
    garbage_patterns = ["&magic=", "&prog=", "&utm"]
    for pattern in garbage_patterns:
        if pattern in cleaned:
            actions.append(f"strip_{pattern[1:-1]}")
            cleaned = cleaned.split(pattern)[0]

    # Step 5: Strip URL path suffixes that aren't part of the DOI
    path_suffixes = ["/abstract", "/full", "/pdf", "/epdf", "/summary"]
    for suffix in path_suffixes:
        if cleaned.endswith(suffix):
            actions.append(f"strip_{suffix[1:]}")
            cleaned = cleaned[: -len(suffix)]

    cleaned = cleaned.strip()

    return DOICleanupResult(
        original=doi,
        cleaned=cleaned,
        was_modified=cleaned != doi,
        actions=actions,
    )


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
        )

        if not search_result:
            reference_duplicate_decision = (
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    duplicate_determination=DuplicateDetermination.CANONICAL,
                )
            )
        else:
            # Store both candidate IDs and their ES scores for the scoring step
            candidate_ids = [result.id for result in search_result]
            candidate_scores = {
                str(result.id): result.score for result in search_result
            }
            reference_duplicate_decision = (
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    candidate_canonical_ids=candidate_ids,
                    candidate_canonical_scores=candidate_scores,
                    duplicate_determination=DuplicateDetermination.NOMINATED,
                )
            )

        return reference_duplicate_decision

    async def _score_candidates(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDeterminationResult:
        """
        Score candidate canonicals and determine duplicate status.

        Uses dedup_lab's PairScorer to compare the source reference against each
        candidate canonical. Returns DUPLICATE if a high-confidence match is found,
        CANONICAL if no candidates score above the threshold, or UNRESOLVED if
        scores fall in the ambiguous middle range.

        :param reference_duplicate_decision: The decision with candidate IDs to score.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The determination result with optional canonical reference.
        :rtype: ReferenceDuplicateDeterminationResult
        """
        # Load the source reference with enhancements and identifiers
        source_reference = await self.sql_uow.references.get_by_pk(
            reference_duplicate_decision.reference_id,
            preload=["enhancements", "identifiers"],
        )

        # Load all candidate references
        candidate_ids = reference_duplicate_decision.candidate_canonical_ids
        if not candidate_ids:
            return ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.CANONICAL,
                detail="No candidates to score.",
            )

        # Get ES scores from the decision (stored as string keys)
        es_scores_str = reference_duplicate_decision.candidate_canonical_scores or {}
        es_scores = {uuid.UUID(k): v for k, v in es_scores_str.items()}

        candidates: list[Reference] = []
        for cand_id in candidate_ids:
            cand = await self.sql_uow.references.get_by_pk(
                cand_id,
                preload=["enhancements", "identifiers"],
            )
            candidates.append(cand)

        # Convert to deduplication views for scoring
        source_view = ReferenceDeduplicationView.from_reference(source_reference)
        candidate_views = [
            ReferenceDeduplicationView.from_reference(c) for c in candidates
        ]

        # Create scorer and score all candidates
        scorer = _create_scorer()

        # Use ES+Jaccard scoring with stored ES scores
        scored_candidates = scorer.score_source_two_stage(
            source_view,
            candidate_views,
            es_scores=es_scores,
            top_k=settings.dedup_scoring.two_stage_top_k,
        )

        if not scored_candidates:
            return ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.CANONICAL,
                detail="No candidates after scoring.",
            )

        # Get the best match
        best_candidate, best_score = scored_candidates[0]
        best_reference_id = best_candidate.id

        # Build detail string with top scores
        top_scores = [
            f"{cand.id}: {score.combined_score:.3f} ({score.confidence.value})"
            for cand, score in scored_candidates[:3]
        ]
        detail = f"Top scores: {'; '.join(top_scores)}"

        # Decision logic based on thresholds
        score_str = f"score={best_score.combined_score:.3f}"
        if best_score.confidence == ConfidenceLevel.HIGH:
            # High confidence match - mark as duplicate
            return ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.DUPLICATE,
                canonical_reference_id=best_reference_id,
                detail=f"High confidence match ({score_str}). {detail}",
            )

        if best_score.confidence == ConfidenceLevel.MEDIUM:
            # Medium confidence - needs manual review
            return ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.UNRESOLVED,
                detail=f"Medium confidence match ({score_str}). {detail}",
            )

        # Low confidence - no good match found, mark as canonical
        return ReferenceDuplicateDeterminationResult(
            duplicate_determination=DuplicateDetermination.CANONICAL,
            detail=f"No high-confidence match (best={score_str}). {detail}",
        )

    async def determine_canonical_from_candidates(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDecision:
        """
        Determine a canonical reference from its candidates.

        Uses the dedup_lab PairScorer to compare the source reference against
        candidate canonicals and make a determination based on similarity scores.

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

        duplicate_determination_result = await self._score_candidates(
            reference_duplicate_decision
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
        if not trusted_identifiers:
            return None

        # Check if any DOI needs cleanup - if so, flag for robot validation
        # DOIs with cruft (HTML entities, query params, etc.) should be validated
        # via Crossref before being trusted for deduplication
        for ti in trusted_identifiers:
            if ti.identifier_type == ExternalIdentifierType.DOI:
                cleanup_result = clean_doi(ti.identifier)
                if cleanup_result.was_modified:
                    return [
                        await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                            reference_duplicate_decision.id,
                            duplicate_determination=DuplicateDetermination.UNRESOLVED,
                            detail=(
                                f"DOI needs validation: original='{cleanup_result.original}' "
                                f"cleaned='{cleanup_result.cleaned}' "
                                f"actions={cleanup_result.actions}"
                            ),
                        )
                    ]

        # Check if ref has OpenAlex ID (globally unique, authoritative)
        has_openalex_id = any(
            ti.identifier_type == ExternalIdentifierType.OPEN_ALEX
            for ti in trusted_identifiers
        )

        candidates = await self.sql_uow.references.find_with_identifiers(
            trusted_identifiers,
            preload=["duplicate_decision", "identifiers"],
            match="any",
        )
        candidates = [
            candidate for candidate in candidates if candidate.id != reference.id
        ]

        # Check for conflicting trusted identifiers:
        # If incoming ref has OpenAlex ID and candidates have DIFFERENT OpenAlex IDs,
        # this indicates bad DOI metadata (multiple OpenAlex works sharing a DOI).
        # Mark as UNRESOLVED for review rather than trusting the DOI.
        if has_openalex_id and candidates:
            incoming_openalex_ids = {
                ti.identifier
                for ti in trusted_identifiers
                if ti.identifier_type == ExternalIdentifierType.OPEN_ALEX
            }

            for candidate in candidates:
                if not candidate.identifiers:
                    continue
                candidate_openalex_ids = {
                    ident.identifier.identifier
                    for ident in candidate.identifiers
                    if ident.identifier.identifier_type == ExternalIdentifierType.OPEN_ALEX
                }
                # If candidate has OpenAlex ID(s) that don't match incoming ref's
                if candidate_openalex_ids and not (
                    incoming_openalex_ids & candidate_openalex_ids
                ):
                    # Conflict: same DOI but different OpenAlex IDs
                    # Get the conflicting DOIs for the detail message
                    incoming_dois = {
                        ti.identifier
                        for ti in trusted_identifiers
                        if ti.identifier_type == ExternalIdentifierType.DOI
                    }
                    return [
                        await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                            reference_duplicate_decision.id,
                            duplicate_determination=DuplicateDetermination.UNRESOLVED,
                            detail=(
                                f"Conflicting trusted identifiers: shared DOI(s) "
                                f"{incoming_dois} but different OpenAlex IDs "
                                f"(incoming: {incoming_openalex_ids}, "
                                f"existing: {candidate_openalex_ids}). "
                                "Likely malformed DOI in source data."
                            ),
                        )
                    ]

        if not candidates:
            # No existing ref with this identifier
            if has_openalex_id:
                # OpenAlex IDs are globally unique - mark as canonical immediately
                # This prevents title-based dedup between different W IDs
                updated_decision = await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    duplicate_determination=DuplicateDetermination.CANONICAL,
                    detail="New OpenAlex record (W ID not in corpus)",
                )
                return [updated_decision]
            # DOI-only refs fall through to title-based dedup
            return None

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
