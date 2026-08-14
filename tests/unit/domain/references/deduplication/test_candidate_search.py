"""Tests for service-side candidate author-query construction."""

from unittest.mock import AsyncMock

import pytest
from elastic_transport import ApiResponseMeta, ConnectionTimeout
from elastic_transport import ConnectionError as ESConnectionError
from elasticsearch import ApiError
from elasticsearch.dsl import AsyncSearch

from app.core.config import DedupCandidateScoringConfig
from app.core.exceptions import ESError
from app.domain.references.models.models import (
    CandidateCanonicalSearchQuery,
    DuplicateDetermination,
)
from app.domain.references.repository import ReferenceESRepository
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


class TestCandidateSearchFailureTranslation:
    """Transient Elasticsearch failures become ESError; defects stay fatal."""

    @staticmethod
    def _api_error(status: int) -> ApiError:
        meta = ApiResponseMeta(
            status=status, http_version="1.1", headers={}, duration=0.0, node=None
        )
        return ApiError("elasticsearch said no", meta=meta, body=None)

    async def _search(self, monkeypatch, error: Exception):
        async def execute(_self):
            raise error

        monkeypatch.setattr(AsyncSearch, "execute", execute)
        repository = ReferenceESRepository(client=AsyncMock())
        return await repository.search_for_candidate_canonicals(
            CandidateCanonicalSearchQuery(
                title="A study",
                title_fuzziness="AUTO",
                title_boost=1.0,
                title_operator="or",
                title_minimum_should_match="50%",
                author_terms=("Jane Doe",),
                author_tie_breaker=0.3,
                publication_year_range=(2023, 2025),
                duplicate_determination=DuplicateDetermination.CANONICAL,
                excluded_reference_id=None,
            ),
            k=10,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(ConnectionTimeout("timed out"), id="timeout"),
            pytest.param(ESConnectionError("refused"), id="connection"),
        ],
    )
    async def test_transport_failure_becomes_es_error(self, monkeypatch, error):
        with pytest.raises(ESError):
            await self._search(monkeypatch, error)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    async def test_transient_status_becomes_es_error(self, monkeypatch, status):
        with pytest.raises(ESError):
            await self._search(monkeypatch, self._api_error(status))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 404])
    async def test_client_error_stays_fatal(self, monkeypatch, status):
        """A malformed query is a defect: it must not be retried per record."""
        with pytest.raises(ApiError):
            await self._search(monkeypatch, self._api_error(status))
