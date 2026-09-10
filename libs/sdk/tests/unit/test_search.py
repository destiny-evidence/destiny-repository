"""Tests for the search result models."""

import pytest
from destiny_sdk.references import ReferenceSearchResult
from destiny_sdk.search import SearchResultTotal


def _search_response(page: dict) -> dict:
    return {
        "references": [],
        "total": {"count": 45, "is_lower_bound": False},
        "page": page,
    }


def test_search_result_reads_the_max_result_window():
    result = ReferenceSearchResult.model_validate(
        _search_response({"count": 5, "number": 3, "max_result_window": 10_000})
    )

    assert result.page.max_result_window == 10_000


def test_search_result_tolerates_a_server_without_a_max_result_window():
    result = ReferenceSearchResult.model_validate(
        _search_response({"count": 5, "number": 3})
    )

    assert result.page.max_result_window is None


def test_total_defaults_is_lower_bound_to_false():
    total = SearchResultTotal.model_validate({"count": 45})

    with pytest.warns(DeprecationWarning):
        assert total.is_lower_bound is False


def test_total_parses_an_explicitly_sent_lower_bound():
    total = SearchResultTotal.model_validate({"count": 45, "is_lower_bound": True})

    with pytest.warns(DeprecationWarning):
        assert total.is_lower_bound is True


def test_is_lower_bound_is_marked_deprecated_in_the_schema():
    schema = SearchResultTotal.model_json_schema()

    assert schema["properties"]["is_lower_bound"]["deprecated"] is True
