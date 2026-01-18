"""Pair scoring for deduplication using ES+Jaccard algorithm."""

from typing import TYPE_CHECKING
from uuid import UUID

from app.domain.references.deduplication.scoring.models import (
    ConfidenceLevel,
    ReferenceDeduplicationView,
    ScoringResult,
)
from app.domain.references.deduplication.scoring.utils import (
    title_token_jaccard,
    tokenize,
)

if TYPE_CHECKING:
    from app.core.config import DedupScoringConfig


class PairScorer:
    """
    Scorer for deduplication using ES+Jaccard algorithm.

    This implements a two-stage scoring approach:
    1. Identifier short-circuit: Check for OpenAlex ID or DOI matches
    2. ES+Jaccard verification: Use ES BM25 scores + title Jaccard similarity

    The algorithm prioritizes precision over recall - it's better to miss a
    duplicate than to incorrectly merge distinct works.

    Benchmark results (100k corpus):
    - Precision: 99.8%
    - Recall: 94.4% (100% with identifier shortcut)
    - F1: 0.970
    """

    def __init__(self, config: "DedupScoringConfig") -> None:
        """
        Initialize the scorer with configuration.

        Args:
            config: Deduplication scoring configuration with thresholds.

        """
        self.config = config

    def score_source_two_stage(
        self,
        source: ReferenceDeduplicationView,
        candidates: list[ReferenceDeduplicationView],
        es_scores: dict[UUID, float],
        top_k: int = 10,
    ) -> list[tuple[ReferenceDeduplicationView, ScoringResult]]:
        """
        Score candidates against source using ES+Jaccard algorithm.

        Candidates are sorted by ES score and the top-k are evaluated.
        Returns scored candidates sorted by combined score (descending).

        Args:
            source: The source reference to find duplicates for.
            candidates: List of candidate references from ES search.
            es_scores: Dictionary mapping candidate IDs to ES BM25 scores.
            top_k: Maximum number of candidates to evaluate (default 10).

        Returns:
            List of (candidate, score_result) tuples, sorted by score descending.

        """
        if not candidates:
            return []

        # Sort candidates by ES score (descending) and take top_k
        sorted_candidates = sorted(
            candidates,
            key=lambda c: es_scores.get(c.id, 0.0) if c.id else 0.0,
            reverse=True,
        )[:top_k]

        results: list[tuple[ReferenceDeduplicationView, ScoringResult]] = []

        for candidate in sorted_candidates:
            es_score = es_scores.get(candidate.id, 0.0) if candidate.id else 0.0
            score_result = self._score_pair(source, candidate, es_score)
            results.append((candidate, score_result))

        # Sort by combined score descending
        return sorted(results, key=lambda x: -x[1].combined_score)

    def _score_pair(
        self,
        source: ReferenceDeduplicationView,
        candidate: ReferenceDeduplicationView,
        es_score: float,
    ) -> ScoringResult:
        """
        Score a single source-candidate pair.

        Implements the ES+Jaccard algorithm with identifier short-circuit:
        1. OpenAlex ID match -> HIGH confidence (always safe)
        2. DOI match with safety gate -> HIGH confidence
        3. ES score >= 100 -> HIGH confidence
        4. ES score >= 50 + Jaccard >= 0.6 -> MEDIUM confidence
        5. Short title (<=2 tokens) + ES >= 20 + Jaccard >= 0.99 -> MEDIUM
        6. Otherwise -> LOW confidence (not a duplicate)

        Args:
            source: Source reference being deduplicated.
            candidate: Candidate reference from corpus.
            es_score: Elasticsearch BM25 score for this candidate.

        Returns:
            ScoringResult with confidence level and scores.

        """
        # Calculate Jaccard upfront (needed for multiple checks)
        jaccard = title_token_jaccard(source.title, candidate.title)
        src_tokens = len(tokenize(source.title))

        # Check for identifier matches first (short-circuit path)
        id_result = self._check_identifier_match(
            source, candidate, src_tokens, es_score, jaccard
        )
        if id_result:
            return id_result

        # Step 3: ES high score threshold (requires minimum Jaccard to prevent
        # false positives from papers with large author lists where single-letter
        # initials inflate ES scores - e.g., CERN papers with 2900+ authors)
        if (
            es_score >= self.config.es_high_score_threshold
            and jaccard >= self.config.high_score_min_jaccard
        ):
            return ScoringResult(
                combined_score=0.95,
                confidence=ConfidenceLevel.HIGH,
                es_score=es_score,
                jaccard_score=jaccard,
                id_match_type=None,
            )
        # If high ES but low Jaccard, fall through to medium check

        # Step 4: ES + Jaccard verification
        if (
            es_score >= self.config.es_min_score_threshold
            and jaccard >= self.config.jaccard_threshold
        ):
            # Combined score based on ES and Jaccard
            combined = 0.5 + (jaccard * 0.3) + (min(es_score, 100) / 100 * 0.2)
            return ScoringResult(
                combined_score=combined,
                confidence=ConfidenceLevel.MEDIUM,
                es_score=es_score,
                jaccard_score=jaccard,
                id_match_type=None,
            )

        # Step 5: Title quality fallback for short titles
        if (
            src_tokens <= self.config.short_title_max_tokens
            and es_score >= self.config.short_title_min_es_score
            and jaccard >= self.config.short_title_min_jaccard
        ):
            return ScoringResult(
                combined_score=0.7,
                confidence=ConfidenceLevel.MEDIUM,
                es_score=es_score,
                jaccard_score=jaccard,
                id_match_type=None,
            )

        # Step 6: Low confidence - not a duplicate
        # Combined score reflects partial match quality for ranking
        combined = jaccard * 0.5 + (min(es_score, 100) / 100 * 0.3)
        return ScoringResult(
            combined_score=combined,
            confidence=ConfidenceLevel.LOW,
            es_score=es_score,
            jaccard_score=jaccard,
            id_match_type=None,
        )

    def _check_identifier_match(
        self,
        source: ReferenceDeduplicationView,
        candidate: ReferenceDeduplicationView,
        src_tokens: int,
        es_score: float,
        jaccard: float,
    ) -> ScoringResult | None:
        """Check for identifier-based matches (OpenAlex ID or DOI)."""
        # Step 1: OpenAlex ID match (always safe - globally unique)
        if (
            source.openalex_id
            and candidate.openalex_id
            and source.openalex_id == candidate.openalex_id
        ):
            return ScoringResult(
                combined_score=1.0,
                confidence=ConfidenceLevel.HIGH,
                es_score=es_score,
                jaccard_score=jaccard,
                id_match_type="openalex",
            )

        # Step 2: DOI match with safety gate (applied uniformly to all records)
        if source.doi and candidate.doi and source.doi.lower() == candidate.doi.lower():
            # Require corroborating evidence to avoid DOI collision issues
            has_year = bool(source.publication_year)
            has_authors = bool(source.authors)
            min_tokens = self.config.doi_safety_min_title_tokens
            if has_year and (has_authors or src_tokens >= min_tokens):
                return ScoringResult(
                    combined_score=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    es_score=es_score,
                    jaccard_score=jaccard,
                    id_match_type="doi_safe",
                )

        return None
