"""Score reference pairs with the released Deduper."""

import asyncio
from typing import TYPE_CHECKING, cast

from destiny_deduper import FieldStatus, PairScoreResult, get_library_info
from destiny_deduper.data_models import Paper
from destiny_deduper.dedupe import Deduper
from destiny_deduper.logger import logger as deduper_logger

from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    DeduperMetadata,
    DeduplicationFieldComparison,
    DeduplicationFieldStatus,
    DeduplicationPairResult,
    DeduplicationPaper,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

logger = get_logger(__name__)

# Disable the library's per-pair stderr logging; runs can score many pairs.
deduper_logger.disable("destiny_deduper")

# Missing sides are positional; ``_run_deduper`` always passes incoming as A.
FIELD_STATUSES = {
    FieldStatus.COMPARED: DeduplicationFieldStatus.COMPARED,
    FieldStatus.MISSING_A: DeduplicationFieldStatus.MISSING_INCOMING,
    FieldStatus.MISSING_B: DeduplicationFieldStatus.MISSING_CANDIDATE,
    FieldStatus.MISSING_BOTH: DeduplicationFieldStatus.MISSING_BOTH,
}


def _compared_values(paper: DeduplicationPaper) -> "dict[str, JsonValue]":
    """Return JSON values keyed by scorer fields."""
    values = cast("dict[str, JsonValue]", paper.model_dump(mode="json"))
    if paper.authors is not None:
        # The comparator reads only display names.
        values["authors"] = [author.display_name for author in paper.authors]
    return values


def _to_pair_result(
    scored: PairScoreResult,
    incoming: DeduplicationPaper,
    candidate: DeduplicationPaper,
) -> DeduplicationPairResult:
    """Translate one Deduper result into the pair result the assessment records."""
    # The Deduper stringifies object values as Python reprs.
    incoming_values = _compared_values(incoming)
    candidate_values = _compared_values(candidate)
    return DeduplicationPairResult(
        # Unscorable pairs use 0.0 as a placeholder, not a score.
        probability=None if scored.unscorable_reason else scored.probability,
        field_comparisons={
            field: DeduplicationFieldComparison(
                incoming_value=incoming_values.get(field, field_result.value_a),
                candidate_value=candidate_values.get(field, field_result.value_b),
                normalised_incoming_value=field_result.normalised_value_a,
                normalised_candidate_value=field_result.normalised_value_b,
                status=FIELD_STATUSES[field_result.status],
                score=field_result.score,
            )
            for field, field_result in scored.field_results.items()
        },
        early_stop_reason=scored.early_stop_reason,
        doi_mismatch_adjusted=scored.doi_mismatch_adjustment_applied,
        suggested_label=scored.label,
        unscorable_reason=scored.unscorable_reason,
    )


class DeduperPairScorer:
    """Score pairs with the released Deduper, carrying its per-field evidence."""

    def __init__(self) -> None:
        """Read the loaded Deduper's identity and configuration once."""
        library_info = get_library_info()
        self._metadata = DeduperMetadata(
            package_version=library_info.package_version,
            configuration_hash=library_info.config_hash,
            threshold=library_info.decision_threshold,
            effective_configuration=cast(
                "dict[str, JsonValue]", library_info.scoring_config
            ),
        )

    @property
    def metadata(self) -> DeduperMetadata:
        """Return the scorer identity and fixed configuration."""
        return self._metadata

    async def score_pair(
        self,
        incoming: DeduplicationPaper,
        candidate: DeduplicationPaper,
    ) -> DeduplicationPairResult:
        """Score one incoming-reference and candidate pair."""
        # Synchronous and CPU-bound, so it goes off the loop. Score pairs one at a
        # time: loop stall grows with the number in flight, not with the work.
        return await asyncio.to_thread(_score, incoming, candidate)


def _run_deduper(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> PairScoreResult:
    """Build the Deduper's own records and score them, incoming first."""
    incoming_paper = Paper(**incoming.model_dump(exclude_none=True))
    candidate_paper = Paper(**candidate.model_dump(exclude_none=True))
    # The constructor requires the same records ``score_pair`` receives.
    deduper = Deduper(reference=incoming_paper, candidates=[candidate_paper])
    return deduper.score_pair(incoming_paper, candidate_paper)


def _score(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> DeduplicationPairResult:
    """Score one pair, guarding the Deduper's own execution and nothing else."""
    try:
        scored = _run_deduper(incoming, candidate)
    except Exception as exc:
        # Record only the type; exception messages may contain reference values.
        logger.exception("Deduper failed to score a pair")
        return DeduplicationPairResult(
            unscorable_reason=f"Deduper raised {type(exc).__name__}"
        )
    # Translation failures are adapter defects, not unscorable pairs.
    return _to_pair_result(scored, incoming, candidate)
