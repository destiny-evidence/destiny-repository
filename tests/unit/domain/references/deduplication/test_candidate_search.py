"""Tests for service-side candidate author-query construction."""

from app.core.config import DedupCandidateScoringConfig
from app.domain.references.services.deduplication_service import (
    _candidate_author_terms,
)

_CONFIG_DEFAULTS = DedupCandidateScoringConfig()


def _queries(
    authors: list[str],
    *,
    max_clauses: int = _CONFIG_DEFAULTS.max_author_clauses,
    min_token_length: int = _CONFIG_DEFAULTS.min_author_token_length,
) -> tuple[str, ...]:
    config = DedupCandidateScoringConfig(
        max_author_clauses=max_clauses,
        min_author_token_length=min_token_length,
    )
    return _candidate_author_terms(authors, scoring_config=config)


class TestBuildCandidateAuthorQueries:
    def test_empty_authors(self):
        assert _queries([]) == ()

    def test_single_author(self):
        assert _queries(["George Harrison"]) == ("George Harrison",)

    def test_multiple_authors(self):
        assert len(_queries(["George Harrison", "Ringo Starr", "Paul McCartney"])) == 3

    def test_max_clauses_limits_queries(self):
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        authors = [
            f"Author {alphabet[i]}{alphabet[j]}" for i in range(5) for j in range(6)
        ]
        assert len(_queries(authors, max_clauses=10)) == 10

    def test_large_author_list_caps_at_default(self):
        """200 authors still produces a query, capped at the default max_clauses."""
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        authors = [
            f"Author {alphabet[i]}{alphabet[j]}" for i in range(8) for j in range(26)
        ][:200]
        assert len(_queries(authors)) == _CONFIG_DEFAULTS.max_author_clauses

    def test_filters_single_letter_initials(self):
        match_value = _queries(["G Harrison"])[0]
        assert "harrison" in match_value.lower()
        assert "g" not in match_value.lower().split()

    def test_author_with_only_initials_excluded(self):
        assert _queries(["J S"]) == ()
        assert _queries(["É D"]) == ()

    def test_mixed_authors_some_filtered(self):
        """Only authors with meaningful tokens produce clauses."""
        assert _queries(["G H", "Ringo Starr", "P M"]) == ("Ringo Starr",)

    def test_max_clauses_skips_invalid_authors(self):
        assert _queries(["G H", "Ringo Starr"], max_clauses=1) == ("Ringo Starr",)

    def test_min_token_length_custom(self):
        # "John" and "Paul" are both 4 chars.
        assert _queries(["John Paul"], min_token_length=5) == ()
        assert _queries(["John Paul"], min_token_length=4) == ("John Paul",)

    def test_preserves_meaningful_tokens(self):
        match_value = _queries(["George Harrison"])[0]
        assert "George" in match_value
        assert "Harrison" in match_value

    def test_preserves_non_ascii_tokens(self):
        queries = _queries(["José Álvarez", "李 雷"])
        assert len(queries) == 2
        assert "José" in queries[0]
        assert "Álvarez" in queries[0]
        assert "李" in queries[1]
        assert "雷" in queries[1]
