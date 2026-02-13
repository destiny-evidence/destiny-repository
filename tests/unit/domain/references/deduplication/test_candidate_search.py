"""Tests for _build_author_dis_max_query in repository.py."""

from app.core.config import DedupCandidateScoringConfig
from app.domain.references.repository import _build_author_dis_max_query

_CONFIG_DEFAULTS = DedupCandidateScoringConfig()

_DEFAULTS = {
    "max_clauses": _CONFIG_DEFAULTS.max_author_clauses,
    "min_token_length": _CONFIG_DEFAULTS.min_author_token_length,
}


def _dis_max(result):
    """Extract the dis_max dict from a Q object."""
    return result.to_dict()["dis_max"]


class TestBuildAuthorDisMaxQuery:
    def test_empty_authors(self):
        assert _build_author_dis_max_query([], **_DEFAULTS) is None

    def test_single_author(self):
        result = _build_author_dis_max_query(["George Harrison"], **_DEFAULTS)
        assert result is not None
        queries = _dis_max(result)["queries"]
        assert len(queries) == 1
        assert "authors" in queries[0]["match"]

    def test_multiple_authors(self):
        result = _build_author_dis_max_query(
            ["George Harrison", "Ringo Starr", "Paul McCartney"], **_DEFAULTS
        )
        assert result is not None
        assert len(_dis_max(result)["queries"]) == 3

    def test_max_clauses_limits_queries(self):
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        authors = [
            f"Author {alphabet[i]}{alphabet[j]}" for i in range(5) for j in range(6)
        ]
        result = _build_author_dis_max_query(
            authors,
            max_clauses=10,
            min_token_length=_CONFIG_DEFAULTS.min_author_token_length,
        )
        assert result is not None
        assert len(_dis_max(result)["queries"]) == 10

    def test_large_author_list_caps_at_default(self):
        """200 authors still produces a query, capped at the default max_clauses."""
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        authors = [
            f"Author {alphabet[i]}{alphabet[j]}" for i in range(8) for j in range(26)
        ][:200]
        result = _build_author_dis_max_query(authors, **_DEFAULTS)
        assert result is not None
        assert len(_dis_max(result)["queries"]) == _CONFIG_DEFAULTS.max_author_clauses

    def test_filters_single_letter_initials(self):
        result = _build_author_dis_max_query(["G Harrison"], **_DEFAULTS)
        assert result is not None
        match_value = _dis_max(result)["queries"][0]["match"]["authors"]
        assert "harrison" in match_value.lower()
        assert "g" not in match_value.lower().split()

    def test_author_with_only_initials_excluded(self):
        assert _build_author_dis_max_query(["J S"], **_DEFAULTS) is None
        assert _build_author_dis_max_query(["É D"], **_DEFAULTS) is None

    def test_mixed_authors_some_filtered(self):
        """Only authors with meaningful tokens produce clauses."""
        result = _build_author_dis_max_query(["G H", "Ringo Starr", "P M"], **_DEFAULTS)
        assert result is not None
        assert len(_dis_max(result)["queries"]) == 1

    def test_max_clauses_skips_invalid_authors(self):
        result = _build_author_dis_max_query(
            ["G H", "Ringo Starr"],
            max_clauses=1,
            min_token_length=_CONFIG_DEFAULTS.min_author_token_length,
        )
        assert result is not None
        assert len(_dis_max(result)["queries"]) == 1

    def test_min_token_length_custom(self):
        # "Ringo" and "Starr" are both 5 chars
        assert (
            _build_author_dis_max_query(
                ["Ringo Starr"],
                max_clauses=_CONFIG_DEFAULTS.max_author_clauses,
                min_token_length=6,
            )
            is None
        )
        assert (
            _build_author_dis_max_query(
                ["Ringo Starr"],
                max_clauses=_CONFIG_DEFAULTS.max_author_clauses,
                min_token_length=5,
            )
            is not None
        )

    def test_preserves_meaningful_tokens(self):
        result = _build_author_dis_max_query(["George Harrison"], **_DEFAULTS)
        assert result is not None
        match_value = _dis_max(result)["queries"][0]["match"]["authors"]
        assert "George" in match_value
        assert "Harrison" in match_value

    def test_preserves_non_ascii_tokens(self):
        result = _build_author_dis_max_query(["José Álvarez", "李 雷"], **_DEFAULTS)
        assert result is not None
        queries = _dis_max(result)["queries"]
        assert len(queries) == 2
        assert "José" in queries[0]["match"]["authors"]
        assert "Álvarez" in queries[0]["match"]["authors"]
        assert "李" in queries[1]["match"]["authors"]
        assert "雷" in queries[1]["match"]["authors"]
