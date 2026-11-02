"""Read-only orchestration for deep-deduplication assessments."""

from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from opentelemetry import trace
from pydantic import ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError

from app.core.exceptions import (
    DeduplicationError,
    DeduplicationNotFoundError,
    DeduplicationValueError,
    ESError,
    ProjectionError,
)
from app.core.telemetry.attributes import Attributes, sample_trace, trace_attribute
from app.domain.references.models.models import (
    SCORED_ENHANCEMENT_TYPES,
    CandidateSelectionInput,
    CandidateSelectionRequest,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    DeduplicationPairResult,
    DeduplicationPaper,
    IdentifierCandidateOutcome,
    OpenAlexRelation,
    Reference,
    RetrievalPolicyName,
    ScoredDeduplicationCandidate,
)
from app.domain.references.models.projections import (
    CandidateReferenceProjection,
    DeduplicationPaperProjection,
)

tracer = trace.get_tracer(__name__)
ASSESSMENT_SPAN = "Assess deduplication candidates"

CandidateSelector = Callable[
    [CandidateSelectionRequest], Awaitable[CandidateSelectionResult]
]

# Repository errors and connectivity DBAPI failures are per-record infrastructure.
# Malformed queries and programming defects stay fatal, not one failed row per input.
INFRASTRUCTURE_ERRORS = (ESError, OperationalError, InterfaceError)

# Stored on the pair result, so it stays flat: the candidate id already travels
# beside it on the scored candidate and in the unscorable id list.
UNPROJECTABLE_CANDIDATE_REASON = "Candidate could not be projected for scoring."


def _identifier_surfaced(scored: ScoredDeduplicationCandidate) -> bool:
    return any(route.type == "identifier" for route in scored.candidate.routes)


def _identifier_types(identifier_candidates: list[ScoredDeduplicationCandidate]) -> str:
    return ",".join(
        sorted(
            {
                identifier.identifier_type.value
                for scored in identifier_candidates
                for route in scored.candidate.routes
                if route.type == "identifier"
                for identifier in route.matched_identifiers
            }
        )
    )


def _identifier_outcome(
    identifier_candidates: list[ScoredDeduplicationCandidate],
    identifier_probability: float | None,
    best_probability: float | None,
) -> IdentifierCandidateOutcome:
    """Judge the best identifier-surfaced score against the best score overall."""
    if not identifier_candidates:
        return IdentifierCandidateOutcome.NONE
    if identifier_probability is None:
        return IdentifierCandidateOutcome.UNSCORED
    # Identifier candidates are a subset, so equality means top, ties included.
    if identifier_probability == best_probability:
        return IdentifierCandidateOutcome.TOP
    return IdentifierCandidateOutcome.BEATEN


def _openalex_relation(
    incoming: DeduplicationPaper, top: DeduplicationPaper
) -> OpenAlexRelation:
    if incoming.openalex_id is None or top.openalex_id is None:
        return OpenAlexRelation.ABSENT
    if incoming.openalex_id.identifier == top.openalex_id.identifier:
        return OpenAlexRelation.SAME
    return OpenAlexRelation.DIFFERENT


def _trace_assessment(
    assessment: DeduplicationAssessment,
    incoming: DeduplicationPaper,
    candidate_papers: dict[UUID, DeduplicationPaper],
) -> None:
    """
    Record the scoring summary as bounded span attributes.

    Rare outcomes are kept past throughput sampling: policy is set from them.
    """
    clearing_count = len(assessment.threshold_clearing_candidate_ids)
    unscorable_count = len(assessment.unscorable_candidate_ids)
    best, best_non_winning = assessment.best_scores()
    identifier_candidates = [
        scored
        for scored in assessment.scored_candidates
        if _identifier_surfaced(scored)
    ]
    identifier_probability = max(
        (
            scored.pair_result.probability
            for scored in identifier_candidates
            if scored.pair_result.probability is not None
        ),
        default=None,
    )
    identifier_outcome = _identifier_outcome(
        identifier_candidates, identifier_probability, best
    )
    # Types come from the candidates the reported probability belongs to. With none
    # scored, the probability is None and so matches every identifier candidate.
    reported_identifier_candidates = [
        scored
        for scored in identifier_candidates
        if scored.pair_result.probability == identifier_probability
    ]
    top_paper = next(
        (
            candidate_papers[scored.candidate.reference_id]
            for scored in assessment.scored_candidates
            if best is not None and scored.pair_result.probability == best
        ),
        None,
    )
    openalex_relation = _openalex_relation(incoming, top_paper) if top_paper else None

    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_OUTCOME, assessment.outcome.value
    )
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_SCORED_COUNT,
        len(assessment.scored_candidates) - unscorable_count,
    )
    trace_attribute(Attributes.DEDUPLICATION_ASSESSMENT_CLEARING_COUNT, clearing_count)
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_UNSCORABLE_COUNT, unscorable_count
    )
    trace_attribute(Attributes.DEDUPLICATION_ASSESSMENT_BEST_PROBABILITY, best)
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_BEST_NON_WINNING_PROBABILITY,
        best_non_winning,
    )
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_IDENTIFIER_OUTCOME, identifier_outcome.value
    )
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_IDENTIFIER_TYPES,
        _identifier_types(reported_identifier_candidates) or None,
    )
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_IDENTIFIER_PROBABILITY,
        identifier_probability,
    )
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_IDENTIFIER_CLEARS_THRESHOLD,
        None
        if identifier_probability is None
        else identifier_probability >= assessment.deduper.threshold,
    )
    trace_attribute(
        Attributes.DEDUPLICATION_ASSESSMENT_OPENALEX_RELATION,
        openalex_relation.value if openalex_relation else None,
    )
    early_stops = Counter(
        scored.pair_result.early_stop_reason
        for scored in assessment.scored_candidates
        if scored.pair_result.early_stop_reason is not None
    )
    for reason, count in early_stops.items():
        # Rules are the Deduper's own bounded codes, so the names stay bounded.
        trace.get_current_span().set_attribute(
            f"{Attributes.DEDUPLICATION_ASSESSMENT_EARLY_STOP}.{reason}", count
        )

    if (
        clearing_count > 1
        or identifier_outcome == IdentifierCandidateOutcome.BEATEN
        # Below the threshold a different W-ID is just an unrelated OpenAlex record.
        or (openalex_relation == OpenAlexRelation.DIFFERENT and clearing_count > 0)
    ):
        sample_trace()


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
        incoming: DeduplicationPaper,
        candidate: DeduplicationPaper,
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
        pair_scorer: PairScorer,
    ) -> None:
        """Initialize the service with read-only assessment dependencies."""
        self._candidate_selector = candidate_selector
        self._reference_reader = reference_reader
        self._pair_scorer = pair_scorer

    def _trace_scorer(self) -> None:
        """Record the scorer first, so a failed assessment is still groupable by it."""
        metadata = self._pair_scorer.metadata
        trace_attribute(
            Attributes.DEDUPLICATION_ASSESSMENT_DEDUPER_VERSION,
            metadata.package_version,
        )
        trace_attribute(
            Attributes.DEDUPLICATION_ASSESSMENT_DEDUPER_CONFIGURATION_HASH,
            metadata.configuration_hash,
        )
        trace_attribute(
            Attributes.DEDUPLICATION_ASSESSMENT_THRESHOLD, metadata.threshold
        )

    @staticmethod
    def _to_scorer_paper(reference: Reference) -> DeduplicationPaper:
        """Project a reference into the record the scorer compares."""
        try:
            return DeduplicationPaperProjection.get_from_reference(reference)
        except ProjectionError as exc:
            # ``from exc`` keeps the projection failure as the cause, so the message
            # does not need to restate it.
            msg = f"Cannot build a deduplication paper for {reference.id}"
            raise DeduplicationValueError(msg) from exc

    async def _hydrate_one(self, reference_id: UUID) -> Reference:
        """Read one stored reference, treating an empty result as not-found."""
        hydrated = await self._reference_reader.get_hydrated(
            [reference_id], enhancement_types=list(SCORED_ENHANCEMENT_TYPES)
        )
        if not hydrated:
            msg = f"Could not hydrate incoming deduplication reference: {reference_id}"
            raise DeduplicationNotFoundError(msg)
        return hydrated[0]

    @tracer.start_as_current_span(ASSESSMENT_SPAN)
    async def evaluate(
        self,
        reference_id: UUID,
        *,
        retrieval_policy: RetrievalPolicyName | None = None,
        k: int | None = None,
    ) -> DeduplicationAssessment:
        """Assess a stored reference from one hydrated input snapshot."""
        self._trace_scorer()
        reference = await self._hydrate_one(reference_id)
        candidate_reference = CandidateReferenceProjection.get_from_reference(reference)
        # A reference can project to nothing searchable, which the input model
        # rejects. Convert it rather than let a bare ValidationError escape.
        try:
            selection_input = CandidateSelectionInput(
                title=candidate_reference.title,
                authors=candidate_reference.authors,
                publication_year=candidate_reference.publication_year,
                identifiers=candidate_reference.identifiers,
                excluded_reference_id=reference_id,
            )
        except ValidationError as exc:
            msg = f"Cannot build a candidate query for {reference_id}: {exc}"
            raise DeduplicationValueError(msg) from exc
        return await self._assess(
            reference,
            selection_input,
            retrieval_policy=retrieval_policy,
            k=k,
        )

    @tracer.start_as_current_span(ASSESSMENT_SPAN)
    async def evaluate_supplied(
        self,
        incoming: Reference,
        selection_input: CandidateSelectionInput,
        *,
        retrieval_policy: RetrievalPolicyName | None = None,
        k: int | None = None,
    ) -> DeduplicationAssessment:
        """
        Assess an unimported supplied reference against a query the runner built.

        The caller owns the query payload because it decides which fields and
        identifiers the record presents, and sets ``excluded_reference_id`` when the
        record is already held so it cannot be retrieved as its own candidate.
        """
        self._trace_scorer()
        return await self._assess(
            incoming,
            selection_input,
            retrieval_policy=retrieval_policy,
            k=k,
        )

    async def _assess(
        self,
        incoming: Reference,
        selection_input: CandidateSelectionInput,
        *,
        retrieval_policy: RetrievalPolicyName | None,
        k: int | None,
    ) -> DeduplicationAssessment:
        """Find, hydrate and score every candidate under one assessment."""
        # Reduce here rather than per entrypoint: a supplied record carries whatever
        # its dataset held, and both sides must reach the scorer alike.
        scored_incoming = self._to_scorer_paper(incoming)
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
                    candidate_ids, enhancement_types=list(SCORED_ENHANCEMENT_TYPES)
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
        candidate_papers: dict[UUID, DeduplicationPaper] = {}
        scorer_metadata = self._pair_scorer.metadata.model_copy(deep=True)
        threshold = scorer_metadata.threshold
        for candidate in candidate_selection.candidates:
            try:
                candidate_paper = self._to_scorer_paper(
                    candidates_by_id[candidate.reference_id]
                )
            except DeduplicationValueError:
                # One unprojectable candidate is not a failed assessment; it is a
                # candidate the Deduper was never given a chance to score.
                pair_result = DeduplicationPairResult(
                    unscorable_reason=UNPROJECTABLE_CANDIDATE_REASON
                )
            else:
                candidate_papers[candidate.reference_id] = candidate_paper
                pair_result = await self._pair_scorer.score_pair(
                    incoming=scored_incoming, candidate=candidate_paper
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
        assessment = DeduplicationAssessment(
            incoming_reference_id=incoming.id,
            candidate_selection=candidate_selection,
            deduper=scorer_metadata,
            scored_candidates=scored_candidates,
            outcome=outcome,
            proposed_duplicate_of_id=proposed_duplicate_of_id,
            threshold_clearing_candidate_ids=threshold_clearing_ids,
            unscorable_candidate_ids=unscorable_ids,
        )
        _trace_assessment(assessment, scored_incoming, candidate_papers)
        return assessment

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
