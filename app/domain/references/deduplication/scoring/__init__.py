"""Scoring module for reference deduplication."""

from app.domain.references.deduplication.scoring.models import (
    ConfidenceLevel,
    ReferenceDeduplicationView,
    ScoringResult,
)
from app.domain.references.deduplication.scoring.scorer import PairScorer

__all__ = [
    "ConfidenceLevel",
    "PairScorer",
    "ReferenceDeduplicationView",
    "ScoringResult",
]
