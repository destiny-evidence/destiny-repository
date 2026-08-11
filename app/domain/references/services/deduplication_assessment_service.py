"""Read-only orchestration for deep-deduplication assessments."""

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

import destiny_sdk
from sqlalchemy.exc import InterfaceError, OperationalError

from app.core.exceptions import (
    DeduplicationError,
    DeduplicationNotFoundError,
    DeduplicationValueError,
    ESError,
)
from app.domain.references.models.models import (
    CandidateSelectionInput,
    CandidateSelectionRequest,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    DeduplicationPairResult,
    EnhancementType,
    Reference,
    RetrievalPolicyName,
    ScoredDeduplicationCandidate,
)
from app.domain.references.models.projections import CandidateReferenceProjection
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)

CandidateSelector = Callable[
    [CandidateSelectionRequest], Awaitable[CandidateSelectionResult]
]

# Repository errors and connectivity DBAPI failures are per-record infrastructure.
# Malformed queries and programming defects stay fatal, not one failed row per input.
INFRASTRUCTURE_ERRORS = (ESError, OperationalError, InterfaceError)


class ReferenceReader(Protocol):
    """Reference reads required by assessment orchestration."""

    async def get_hydrated(
        self,
        reference_ids: list[UUID],
        enhancement_types: list[str] | None = None,
        external_identifier_types: list[str] | None = None,
    ) -> list[Reference]:
        """Read full references with optional relationship filters."""
        ...


class PairScorer(Protocol):
    """Pair-scoring contract implemented by a stand-in or toolkit adapter."""

    @property
    def metadata(self) -> DeduperMetadata:
        """Return the scorer identity and fixed configuration."""
        ...

    async def score_pair(
        self,
        incoming: destiny_sdk.references.Reference,
        candidate: destiny_sdk.references.Reference,
    ) -> DeduplicationPairResult:
        """Score one incoming-reference and candidate pair."""
        ...


class DeduplicationAssessmentService:
    """Evaluate references without access to decision or side-effect writers."""

    def __init__(
        self,
        *,
        candidate_selector: CandidateSelector,
        reference_reader: ReferenceReader,
        anti_corruption_service: ReferenceAntiCorruptionService,
        pair_scorer: PairScorer,
    ) -> None:
        """Initialize the service with read-only assessment dependencies."""
        self._candidate_selector = candidate_selector
        self._reference_reader = reference_reader
        self._anti_corruption_service = anti_corruption_service
        self._pair_scorer = pair_scorer

    async def evaluate(
        self,
        reference_id: UUID,
        *,
        retrieval_policy: RetrievalPolicyName | None = None,
        k: int | None = None,
    ) -> DeduplicationAssessment:
        """Assess a stored reference from one hydrated input snapshot."""
        hydrated = await self._reference_reader.get_hydrated(
            [reference_id], enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
        )
        if not hydrated:
            msg = f"Could not hydrate incoming deduplication reference: {reference_id}"
            raise DeduplicationNotFoundError(msg)
        reference = hydrated[0]
        incoming = await self._anti_corruption_service.internal_reference_to_sdk(
            reference
        )
        candidate_reference = CandidateReferenceProjection.get_from_reference(reference)
        return await self._assess(
            incoming,
            CandidateSelectionInput(
                title=candidate_reference.title,
                authors=candidate_reference.authors,
                publication_year=candidate_reference.publication_year,
                identifiers=candidate_reference.identifiers,
                excluded_reference_id=reference_id,
            ),
            retrieval_policy=retrieval_policy,
            k=k,
        )

    async def evaluate_supplied(
        self,
        incoming: destiny_sdk.references.Reference,
        selection_input: CandidateSelectionInput,
        *,
        retrieval_policy: RetrievalPolicyName | None = None,
        k: int | None = None,
    ) -> DeduplicationAssessment:
        """
        Assess a frozen SDK reference against a query the runner built.

        The caller owns the query payload because it decides which fields and
        identifiers the record presents, and sets ``excluded_reference_id`` when the
        record is already held so it cannot be retrieved as its own candidate.
        """
        return await self._assess(
            incoming,
            selection_input,
            retrieval_policy=retrieval_policy,
            k=k,
        )

    async def _assess(
        self,
        incoming: destiny_sdk.references.Reference,
        selection_input: CandidateSelectionInput,
        *,
        retrieval_policy: RetrievalPolicyName | None,
        k: int | None,
    ) -> DeduplicationAssessment:
        """Find, hydrate and score every candidate under one assessment."""
        try:
            candidate_selection = await self._candidate_selector(
                CandidateSelectionRequest(
                    input=selection_input,
                    retrieval_policy=retrieval_policy,
                    k=k,
                    hydrate=False,
                )
            )
        except INFRASTRUCTURE_ERRORS as exc:
            msg = f"Candidate retrieval failed ({type(exc).__name__}): {exc}"
            raise DeduplicationError(msg) from exc

        if any(
            candidate.reference_id == incoming.id
            for candidate in candidate_selection.candidates
        ):
            msg = f"Cannot assess reference as a duplicate of itself: {incoming.id}"
            raise DeduplicationValueError(msg)

        candidate_ids = [
            candidate.reference_id for candidate in candidate_selection.candidates
        ]
        candidates_by_id: dict[UUID, Reference] = {}
        if candidate_ids:
            # Only the fields the scorer compares. Loading every type would also
            # sign a URL per full-text enhancement, on a path that never reads one.
            try:
                hydrated = await self._reference_reader.get_hydrated(
                    candidate_ids, enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
                )
            except INFRASTRUCTURE_ERRORS as exc:
                msg = f"Candidate hydration failed ({type(exc).__name__}): {exc}"
                raise DeduplicationError(msg) from exc
            candidates_by_id = {candidate.id: candidate for candidate in hydrated}
            missing_ids = [
                candidate_id
                for candidate_id in candidate_ids
                if candidate_id not in candidates_by_id
            ]
            if missing_ids:
                missing = ", ".join(str(missing_id) for missing_id in missing_ids)
                msg = f"Could not hydrate deduplication candidates: {missing}"
                raise DeduplicationError(msg)

        scored_candidates = []
        threshold_clearing_ids = []
        unscorable_ids = []
        scorer_metadata = self._pair_scorer.metadata.model_copy(deep=True)
        threshold = scorer_metadata.threshold
        for candidate in candidate_selection.candidates:
            candidate_sdk = (
                await self._anti_corruption_service.internal_reference_to_sdk(
                    candidates_by_id[candidate.reference_id]
                )
            )
            pair_result = await self._pair_scorer.score_pair(
                incoming=incoming, candidate=candidate_sdk
            )
            clears_threshold = (
                pair_result.probability >= threshold
                if pair_result.probability is not None
                else None
            )
            scored_candidates.append(
                ScoredDeduplicationCandidate(
                    candidate=candidate,
                    pair_result=pair_result,
                    clears_threshold=clears_threshold,
                )
            )
            if clears_threshold is True:
                threshold_clearing_ids.append(candidate.reference_id)
            elif clears_threshold is None:
                unscorable_ids.append(candidate.reference_id)

        outcome, proposed_duplicate_of_id = self._summarise(
            threshold_clearing_ids,
            unscorable_ids,
            input_searchable=candidate_selection.input_searchability.searchable,
        )
        return DeduplicationAssessment(
            incoming_reference_id=incoming.id,
            candidate_selection=candidate_selection,
            deduper=scorer_metadata,
            scored_candidates=scored_candidates,
            outcome=outcome,
            proposed_duplicate_of_id=proposed_duplicate_of_id,
            threshold_clearing_candidate_ids=threshold_clearing_ids,
            unscorable_candidate_ids=unscorable_ids,
        )

    @staticmethod
    def _summarise(
        threshold_clearing_ids: list[UUID],
        unscorable_ids: list[UUID],
        *,
        input_searchable: bool,
    ) -> tuple[DeduplicationAssessmentOutcome, UUID | None]:
        """Summarise the candidate set without applying acting-policy guards."""
        if unscorable_ids or len(threshold_clearing_ids) > 1:
            return DeduplicationAssessmentOutcome.NO_PROPOSAL, None
        if threshold_clearing_ids:
            return (
                DeduplicationAssessmentOutcome.PROPOSE_DUPLICATE,
                threshold_clearing_ids[0],
            )
        if not input_searchable:
            return DeduplicationAssessmentOutcome.NO_PROPOSAL, None
        return DeduplicationAssessmentOutcome.PROPOSE_CANONICAL, None
