"""Scoring module for reference deduplication using ES+Jaccard algorithm."""

import re
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Self
from uuid import UUID

import destiny_sdk
from pydantic import UUID4, BaseModel, Field

from app.domain.references.models.models import (
    EnhancementType,
    ExternalIdentifierType,
    Reference,
)

if TYPE_CHECKING:
    from app.core.config import DedupScoringConfig

# Pre-compiled regex for tokenization - extracts alphanumeric sequences
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# Pattern to strip XML/HTML tags (including MathML)
_TAG_PATTERN = re.compile(r"<[^>]+>")


def tokenize(text: str | None) -> list[str]:
    """
    Extract lowercase alphanumeric tokens from text.

    Strips XML/HTML tags (including MathML) before tokenization to avoid
    false positive matches on common tag tokens like "mml", "math", "xmlns".

    Ignores punctuation and returns lowercased tokens.
    Empty or None input returns an empty list.

    Args:
        text: Text to tokenize.

    Returns:
        List of lowercase alphanumeric tokens.

    Examples:
        >>> tokenize("Hello, World!")
        ['hello', 'world']
        >>> tokenize("Einleitung.")
        ['einleitung']
        >>> tokenize(None)
        []
        >>> tokenize('<mml:math xmlns:mml="http://www.w3.org/...">x</mml:math>')
        ['x']

    """
    if not text:
        return []
    # Strip XML/HTML tags before tokenization
    clean_text = _TAG_PATTERN.sub(" ", text)
    return [tok.lower() for tok in _TOKEN_PATTERN.findall(clean_text)]


def title_token_jaccard(t1: str | None, t2: str | None) -> float:
    """
    Compute Jaccard similarity on title tokens.

    This is a fast, simple measure of title similarity that works well
    for duplicate detection when combined with ES BM25 scores.

    Tokenization extracts alphanumeric sequences (ignoring punctuation),
    so "Einleitung." and "Einleitung" are treated as the same token.

    Args:
        t1: First title string.
        t2: Second title string.

    Returns:
        Jaccard similarity (0.0 to 1.0).

    Examples:
        >>> title_token_jaccard("Hello World", "Hello World")
        1.0
        >>> title_token_jaccard("Hello World", "Hello")
        0.5
        >>> title_token_jaccard("Einleitung.", "Einleitung")
        1.0
        >>> title_token_jaccard(None, "Hello")
        0.0

    """
    if not t1 or not t2:
        return 0.0

    tokens1 = set(tokenize(t1))
    tokens2 = set(tokenize(t2))

    if not tokens1 or not tokens2:
        return 0.0

    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)

    return intersection / union


class ConfidenceLevel(StrEnum):
    """Confidence level for duplicate detection decisions."""

    HIGH = auto()
    """High confidence: ES score >= 100 or identifier match. Accept immediately."""
    MEDIUM = auto()
    """Medium confidence: ES score >= 50 with Jaccard verification. Accept."""
    LOW = auto()
    """Low confidence: ES score < 50 or failed Jaccard. Reject as duplicate."""


class ReferenceDeduplicationView(BaseModel):
    """
    Lightweight view of a Reference for deduplication scoring.

    This extracts only the fields needed for duplicate detection, avoiding
    the overhead of full Reference model with all relationships.
    """

    id: UUID4 | None = Field(default=None, description="Reference ID")
    title: str | None = Field(default=None, description="Work title")
    authors: list[str] | None = Field(default=None, description="Author names")
    publication_year: int | None = Field(default=None, description="Publication year")
    doi: str | None = Field(default=None, description="DOI identifier")
    openalex_id: str | None = Field(default=None, description="OpenAlex W ID")
    pmid: str | None = Field(default=None, description="PubMed ID")

    @classmethod
    def from_reference(cls, reference: Reference) -> Self:
        """
        Create a deduplication view from a Reference.

        Extracts bibliographic fields from enhancements and identifiers.
        Requires enhancements and identifiers to be preloaded.

        Args:
            reference: The Reference to extract fields from.

        Returns:
            A ReferenceDeduplicationView with extracted fields.

        """
        # Extract bibliographic fields from enhancements
        title: str | None = None
        authors: list[str] | None = None
        publication_year: int | None = None

        if reference.enhancements:
            # Process enhancements by created_at order (latest wins)
            for enhancement in sorted(
                reference.enhancements,
                key=lambda e: e.created_at.timestamp() if e.created_at else 0,
            ):
                if (
                    enhancement.content.enhancement_type
                    == EnhancementType.BIBLIOGRAPHIC
                ):
                    title = enhancement.content.title or title
                    publication_year = (
                        enhancement.content.publication_year
                        or (
                            enhancement.content.publication_date.year
                            if enhancement.content.publication_date
                            else None
                        )
                        or publication_year
                    )
                    if enhancement.content.authorship:
                        authors = cls._extract_author_names(
                            enhancement.content.authorship
                        )

        # Extract identifiers
        doi: str | None = None
        openalex_id: str | None = None
        pmid: str | None = None

        if reference.identifiers:
            for linked_id in reference.identifiers:
                id_type = linked_id.identifier.identifier_type
                id_value = str(linked_id.identifier.identifier)
                if id_type == ExternalIdentifierType.DOI:
                    doi = id_value
                elif id_type == ExternalIdentifierType.OPEN_ALEX:
                    openalex_id = id_value
                elif id_type == ExternalIdentifierType.PM_ID:
                    pmid = id_value

        return cls(
            id=reference.id,
            title=title,
            authors=authors,
            publication_year=publication_year,
            doi=doi,
            openalex_id=openalex_id,
            pmid=pmid,
        )

    @staticmethod
    def _extract_author_names(
        authorship: list[destiny_sdk.enhancements.Authorship],
    ) -> list[str]:
        """Extract author display names, ordered by position."""
        return [
            author.display_name
            for author in sorted(
                authorship,
                key=lambda author: (
                    {
                        destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
                        destiny_sdk.enhancements.AuthorPosition.LAST: 1,
                    }.get(author.position, 0),
                    author.display_name,
                ),
            )
        ]


class ScoringResult(BaseModel):
    """Result of scoring a candidate against a source reference."""

    combined_score: float = Field(
        description="Combined score (0.0 to 1.0) for duplicate confidence"
    )
    confidence: ConfidenceLevel = Field(description="Confidence level of the decision")
    es_score: float | None = Field(default=None, description="Elasticsearch BM25 score")
    jaccard_score: float | None = Field(
        default=None, description="Title token Jaccard similarity"
    )
    id_match_type: str | None = Field(
        default=None,
        description="Type of identifier match: 'openalex', 'doi_safe', or None",
    )


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


__all__ = [
    "ConfidenceLevel",
    "PairScorer",
    "ReferenceDeduplicationView",
    "ScoringResult",
    "title_token_jaccard",
    "tokenize",
]