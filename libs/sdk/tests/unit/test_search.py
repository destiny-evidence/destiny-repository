"""Tests for the search result models."""

from destiny_sdk.references import ReferenceSearchResult


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
