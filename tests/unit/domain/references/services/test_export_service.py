"""Unit tests for the search-export lifecycle service and reference streaming."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest

from app.domain.references.models.models import (
    ExportFormat,
    SearchExport,
    SearchQuery,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.export_service import SearchExportService
from app.domain.references.services.search_service import SearchService
from app.persistence.es.persistence import ESHit, ESSearchResult, ESSearchTotal
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    BlobStorageFileFactory,
    EnhancementFactory,
    ReferenceFactory,
)

# Undecorated body — tests drive the implementation with mocks instead of a UoW.
_collect_export_ids = SearchExportService._collect_search_export_ids.__wrapped__  # type: ignore[attr-defined]  # noqa: SLF001


def _make_service() -> SearchExportService:
    """Build a minimally-initialised SearchExportService for body-level tests."""
    service = SearchExportService.__new__(SearchExportService)
    service._search_service = SearchService.__new__(SearchService)  # noqa: SLF001
    return service


async def test_collect_search_export_ids_flags_truncated_on_gte_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ES reports `gte` at the cap, the result is flagged as truncated."""
    monkeypatch.setattr(
        SearchService,
        "search",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(10_000)],
                total=ESSearchTotal(value=10_000, relation="gte"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), SearchExport(query=SearchQuery(query_string="climate"))
    )

    assert len(ids) == 10_000
    assert truncated is True


async def test_collect_search_export_ids_flags_truncated_on_eq_above_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ES tracks the exact count past the cap, `eq` total > cap is truncated."""
    monkeypatch.setattr(
        SearchService,
        "search",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(10_000)],
                total=ESSearchTotal(value=25_000, relation="eq"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), SearchExport(query=SearchQuery(query_string="climate"))
    )

    assert len(ids) == 10_000
    assert truncated is True


async def test_collect_search_export_ids_handles_empty_result_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero hits returns ([], False) without crashing."""
    monkeypatch.setattr(
        SearchService,
        "search",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[],
                total=ESSearchTotal(value=0, relation="eq"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), SearchExport(query=SearchQuery(query_string="climate"))
    )

    assert ids == []
    assert truncated is False


async def test_collect_search_export_ids_exactly_at_cap_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result set of exactly 10,000 with `eq` total must not be flagged truncated."""
    monkeypatch.setattr(
        SearchService,
        "search",
        AsyncMock(
            return_value=ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(10_000)],
                total=ESSearchTotal(value=10_000, relation="eq"),
                page=1,
            )
        ),
    )

    ids, truncated = await _collect_export_ids(
        _make_service(), SearchExport(query=SearchQuery(query_string="climate"))
    )

    assert len(ids) == 10_000
    # ES says eq=10_000: it counted exactly to the cap, so we got everything.
    assert truncated is False


def _reference_with_title(title: str):
    ref_id = uuid7()
    bibliographic = EnhancementFactory.build(
        reference_id=ref_id,
        content=BibliographicMetadataEnhancementFactory.build(title=title),
    )
    return ReferenceFactory.build(
        id=ref_id, enhancements=[bibliographic], identifiers=[]
    )


def _identity_access_control():
    acs = MagicMock()
    acs.redact_reference = lambda reference: reference
    return acs


def _reference_service_with(references, anti_corruption_service):
    """A minimally-initialised ReferenceService whose dedup fetch is stubbed."""
    service = ReferenceService.__new__(ReferenceService)
    service._get_deduplicated_references = AsyncMock(  # noqa: SLF001
        return_value=references
    )
    service._anti_corruption_service = anti_corruption_service  # noqa: SLF001
    return service


async def _capture_uploaded_body(reference_service, export_format, reference):
    """Run an export and return the bytes streamed to blob storage, decoded."""
    captured = {}

    async def _capture(*, content, filename, **_):
        captured["content"] = content
        captured["filename"] = filename
        return BlobStorageFileFactory.build()

    blob_repository = MagicMock()
    blob_repository.upload_file_to_blob_storage = AsyncMock(side_effect=_capture)

    result_file, count = await reference_service.stream_references_to_blob(
        reference_ids=[reference.id],
        export_format=export_format,
        access_control_service=_identity_access_control(),
        blob_repository=blob_repository,
        path="search_exports",
        filename=f"{reference.id}.{export_format.extension}",
        chunk_size=100,
    )
    body = b"".join([chunk async for chunk in captured["content"].stream()]).decode()
    return body, count, captured["filename"]


async def test_stream_references_to_blob_serializes_ris() -> None:
    """A RIS export streams a rendered RIS record per reference."""
    reference = _reference_with_title("A Title")
    reference_service = _reference_service_with([reference], AsyncMock())

    body, count, filename = await _capture_uploaded_body(
        reference_service, ExportFormat.RIS, reference
    )

    assert count == 1
    assert filename.endswith(".ris")
    assert body.startswith("TY  - ")
    assert "TI  - A Title" in body
    assert "ER  - " in body


async def test_stream_references_to_blob_serializes_jsonl() -> None:
    """A JSONL export streams the anti-corruption SDK model's jsonl per reference."""
    reference = _reference_with_title("A Title")

    sdk_reference = MagicMock()
    sdk_reference.to_jsonl.return_value = '{"id": "x"}'
    anti_corruption = MagicMock()
    anti_corruption.reference_to_sdk = AsyncMock(return_value=sdk_reference)
    reference_service = _reference_service_with([reference], anti_corruption)

    body, _, filename = await _capture_uploaded_body(
        reference_service, ExportFormat.JSONL, reference
    )

    assert filename.endswith(".jsonl")
    assert body.strip() == '{"id": "x"}'
    anti_corruption.reference_to_sdk.assert_awaited_once_with(reference)


async def test_stream_search_export_uses_format_extension() -> None:
    """The lifecycle service names the blob file with the export format extension."""
    reference_service = MagicMock()
    reference_service.stream_references_to_blob = AsyncMock(
        return_value=(BlobStorageFileFactory.build(), 2)
    )
    service = SearchExportService.__new__(SearchExportService)
    service._reference_service = reference_service  # noqa: SLF001
    service._access_control_service = MagicMock()  # noqa: SLF001
    export = SearchExport(
        query=SearchQuery(query_string="x"), export_format=ExportFormat.RIS
    )

    await SearchExportService._stream_search_export.__wrapped__(  # type: ignore[attr-defined]  # noqa: SLF001
        service, export, [uuid7(), uuid7()], MagicMock()
    )

    kwargs = reference_service.stream_references_to_blob.await_args.kwargs
    assert kwargs["filename"] == f"{export.id}.ris"
    assert kwargs["export_format"] == ExportFormat.RIS


async def test_stream_references_to_blob_jsonl_flattens_duplicates(
    fake_repository, fake_uow
):
    """JSONL export flattens canonical + duplicate enhancements and identifiers."""
    duplicate_ref = ReferenceFactory(duplicate_references=[])
    canonical_ref = ReferenceFactory(duplicate_references=[duplicate_ref])
    reference_service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()),
        fake_uow(references=fake_repository(init_entries=[canonical_ref])),
        fake_uow(),
    )

    body, _, _ = await _capture_uploaded_body(
        reference_service, ExportFormat.JSONL, canonical_ref
    )
    data = json.loads(body.strip())

    canonical_sources = {e.source for e in canonical_ref.enhancements}
    duplicate_sources = {e.source for e in duplicate_ref.enhancements}
    assert {e["source"] for e in data["enhancements"]} == (
        canonical_sources | duplicate_sources
    )
    assert all(e.get("created_at") for e in data["enhancements"])
    assert len(data["identifiers"]) == len(canonical_ref.identifiers) + len(
        duplicate_ref.identifiers
    )
    assert "duplicate_references" not in data
