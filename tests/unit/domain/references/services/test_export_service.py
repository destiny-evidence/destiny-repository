"""Unit tests for ReferenceExportService._collect_reference_export_ids."""

from unittest.mock import AsyncMock
from uuid import uuid7

import pytest

from app.domain.references.models.models import ReferenceExport
from app.domain.references.services.export_service import ReferenceExportService
from app.domain.references.services.search_service import SearchService
from app.persistence.es.persistence import ESHit, ESSearchResult, ESSearchTotal

# Undecorated body — tests drive the implementation with mocks instead of a UoW.
_collect_export_ids = ReferenceExportService._collect_reference_export_ids.__wrapped__  # type: ignore[attr-defined]  # noqa: SLF001


def _make_service() -> ReferenceExportService:
    """Build a minimally-initialised ReferenceExportService for body-level tests."""
    service = ReferenceExportService.__new__(ReferenceExportService)
    service._search_service = SearchService.__new__(SearchService)  # noqa: SLF001
    return service


async def test_collect_reference_export_ids_flags_truncated_on_gte_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ES reports `gte` at the cap, the result is flagged as truncated."""
    monkeypatch.setattr(
        SearchService,
        "search_with_query_string",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(10_000)],
                total=ESSearchTotal(value=10_000, relation="gte"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), ReferenceExport(query="climate")
    )

    assert len(ids) == 10_000
    assert truncated is True


async def test_collect_reference_export_ids_flags_truncated_on_eq_above_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ES tracks the exact count past the cap, `eq` total > cap is truncated."""
    monkeypatch.setattr(
        SearchService,
        "search_with_query_string",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(10_000)],
                total=ESSearchTotal(value=25_000, relation="eq"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), ReferenceExport(query="climate")
    )

    assert len(ids) == 10_000
    assert truncated is True


async def test_collect_reference_export_ids_handles_empty_result_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero hits returns ([], False) without crashing."""
    monkeypatch.setattr(
        SearchService,
        "search_with_query_string",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[],
                total=ESSearchTotal(value=0, relation="eq"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), ReferenceExport(query="climate")
    )

    assert ids == []
    assert truncated is False


async def test_collect_reference_export_ids_exactly_at_cap_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result set of exactly 10,000 with `eq` total must not be flagged truncated."""
    monkeypatch.setattr(
        SearchService,
        "search_with_query_string",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(10_000)],
                total=ESSearchTotal(value=10_000, relation="eq"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), ReferenceExport(query="climate")
    )

    assert len(ids) == 10_000
    # ES says eq=10_000: it counted exactly to the cap, so we got everything.
    assert truncated is False
