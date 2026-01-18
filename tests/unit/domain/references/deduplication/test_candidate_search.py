"""Tests for candidate search helper functions in repository.py.

These functions are used by the ES candidate search to build queries with
bounded author contributions and detect collaboration papers.
"""

from app.domain.references.repository import (
    _build_author_dis_max_query,
    _is_collaboration_paper,
)


class TestIsCollaborationPaper:
    """Tests for _is_collaboration_paper function."""

    def test_small_author_list(self):
        """Small author list is not a collaboration."""
        authors = ["John Smith", "Jane Doe", "Bob Wilson"]
        assert _is_collaboration_paper(authors) is False

    def test_large_author_list_default_threshold(self):
        """More than 50 authors triggers collaboration detection."""
        authors = [f"Author {i}" for i in range(51)]
        assert _is_collaboration_paper(authors) is True

    def test_large_author_list_custom_threshold(self):
        """Custom threshold works."""
        authors = [f"Author {i}" for i in range(25)]
        assert _is_collaboration_paper(authors, threshold=30) is False
        assert _is_collaboration_paper(authors, threshold=20) is True

    def test_atlas_collaboration_keyword(self):
        """ATLAS collaboration keyword in first 5 authors triggers detection."""
        authors = ["ATLAS Collaboration", "John Smith"]
        assert _is_collaboration_paper(authors) is True

    def test_cms_collaboration_keyword(self):
        """CMS collaboration keyword triggers detection."""
        authors = ["J. Doe", "CMS Collaboration", "A. Smith"]
        assert _is_collaboration_paper(authors) is True

    def test_cern_keyword(self):
        """CERN keyword triggers detection."""
        authors = ["CERN Group", "John Smith"]
        assert _is_collaboration_paper(authors) is True

    def test_keyword_case_insensitive(self):
        """Collaboration keywords are case-insensitive."""
        authors = ["atlas collaboration", "John Smith"]
        assert _is_collaboration_paper(authors) is True
        authors = ["ATLAS COLLABORATION", "John Smith"]
        assert _is_collaboration_paper(authors) is True

    def test_keyword_not_in_first_5_authors(self):
        """Keyword only checked in first 5 authors."""
        # Put ATLAS as 6th author
        authors = [f"Author {i}" for i in range(5)] + ["ATLAS Collaboration"]
        # Total is 6 authors, under threshold, keyword is 6th (not checked)
        assert _is_collaboration_paper(authors) is False

    def test_empty_author_list(self):
        """Empty author list is not a collaboration."""
        assert _is_collaboration_paper([]) is False

    def test_exact_threshold_boundary(self):
        """Exactly 50 authors is not a collaboration (>50 required)."""
        authors = [f"Author {i}" for i in range(50)]
        assert _is_collaboration_paper(authors) is False
        authors.append("Author 50")  # Now 51
        assert _is_collaboration_paper(authors) is True


class TestBuildAuthorDisMaxQuery:
    """Tests for _build_author_dis_max_query function."""

    def test_empty_authors(self):
        """Empty author list returns None."""
        result = _build_author_dis_max_query([], max_clauses=25, min_token_length=2)
        assert result is None

    def test_single_author(self):
        """Single author creates single match query."""
        result = _build_author_dis_max_query(
            ["John Smith"], max_clauses=25, min_token_length=2
        )
        assert result is not None
        # Check it's a dis_max query
        assert result.to_dict()["dis_max"] is not None
        assert len(result.to_dict()["dis_max"]["queries"]) == 1

    def test_multiple_authors(self):
        """Multiple authors create multiple match queries."""
        authors = ["John Smith", "Jane Doe", "Bob Wilson"]
        result = _build_author_dis_max_query(
            authors, max_clauses=25, min_token_length=2
        )
        assert result is not None
        assert len(result.to_dict()["dis_max"]["queries"]) == 3

    def test_max_clauses_limits_queries(self):
        """max_clauses limits number of author queries."""
        authors = [f"Author Name {i}" for i in range(30)]
        result = _build_author_dis_max_query(
            authors, max_clauses=10, min_token_length=2
        )
        assert result is not None
        assert len(result.to_dict()["dis_max"]["queries"]) == 10

    def test_filters_single_letter_initials(self):
        """Single-letter tokens (initials) are filtered."""
        # "J Smith" - "J" should be filtered, only "Smith" used
        result = _build_author_dis_max_query(
            ["J Smith"], max_clauses=25, min_token_length=2
        )
        assert result is not None
        query_dict = result.to_dict()
        # The match query should only contain "Smith"
        match_query = query_dict["dis_max"]["queries"][0]["match"]["authors.dedup"]
        assert "smith" in match_query.lower()
        assert " j " not in f" {match_query.lower()} "

    def test_author_with_only_initials_excluded(self):
        """Author with only initials creates no query."""
        # "J S" - both are single letters, should create no query
        result = _build_author_dis_max_query(
            ["J S"], max_clauses=25, min_token_length=2
        )
        # All tokens filtered, so no query
        assert result is None

    def test_mixed_authors_some_filtered(self):
        """Mix of valid authors and initial-only authors."""
        authors = ["J S", "John Smith", "A B"]  # First and third filtered
        result = _build_author_dis_max_query(
            authors, max_clauses=25, min_token_length=2
        )
        assert result is not None
        # Only "John Smith" should produce a query
        assert len(result.to_dict()["dis_max"]["queries"]) == 1

    def test_collaboration_paper_returns_none(self):
        """Collaboration papers (>50 authors) return None."""
        authors = [f"Author {i}" for i in range(60)]
        result = _build_author_dis_max_query(
            authors, max_clauses=25, min_token_length=2
        )
        # Should return None because it's detected as collaboration
        assert result is None

    def test_collaboration_keyword_returns_none(self):
        """Papers with collaboration keywords return None."""
        authors = ["ATLAS Collaboration", "John Smith"]
        result = _build_author_dis_max_query(
            authors, max_clauses=25, min_token_length=2
        )
        assert result is None

    def test_tie_breaker_default(self):
        """Default tie_breaker is 0.1."""
        authors = ["John Smith", "Jane Doe"]
        result = _build_author_dis_max_query(
            authors, max_clauses=25, min_token_length=2
        )
        assert result is not None
        assert result.to_dict()["dis_max"]["tie_breaker"] == 0.1

    def test_custom_tie_breaker(self):
        """Custom tie_breaker is applied."""
        authors = ["John Smith", "Jane Doe"]
        result = _build_author_dis_max_query(
            authors, max_clauses=25, min_token_length=2, tie_breaker=0.3
        )
        assert result is not None
        assert result.to_dict()["dis_max"]["tie_breaker"] == 0.3

    def test_uses_authors_dedup_field(self):
        """Query targets authors.dedup field."""
        result = _build_author_dis_max_query(
            ["John Smith"], max_clauses=25, min_token_length=2
        )
        assert result is not None
        query = result.to_dict()["dis_max"]["queries"][0]
        assert "authors.dedup" in query["match"]

    def test_min_token_length_custom(self):
        """Custom min_token_length filters appropriately."""
        # With min_token_length=3, "Jo" is filtered from "Jo Smith"
        result = _build_author_dis_max_query(
            ["Jo Smith"], max_clauses=25, min_token_length=3
        )
        assert result is not None
        match_query = result.to_dict()["dis_max"]["queries"][0]["match"][
            "authors.dedup"
        ]
        assert "smith" in match_query.lower()
        # "jo" should be filtered (only 2 chars)
        assert match_query.lower().strip() == "smith"

    def test_preserves_meaningful_tokens(self):
        """Meaningful tokens (>= min_length) are preserved."""
        # "John" (4 chars) should be preserved with min_token_length=2
        result = _build_author_dis_max_query(
            ["John Smith"], max_clauses=25, min_token_length=2
        )
        assert result is not None
        match_query = result.to_dict()["dis_max"]["queries"][0]["match"][
            "authors.dedup"
        ]
        assert "john" in match_query.lower()
        assert "smith" in match_query.lower()
