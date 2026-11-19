"""Unit tests for the search-export lifecycle service and reference streaming."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest

from app.core.exceptions import SQLNotFoundError
from app.domain.references.models.models import (
    ExportFormat,
    ExportStatus,
    ReferenceExport,
    SearchExport,
    SearchQuery,
)
from app.domain.references.models.sql import ReferenceExport as SQLReferenceExport
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.export_service import (
    ReferenceExportService,
    SearchExportService,
)
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


@pytest.mark.parametrize(
    ("total", "expected_truncated"),
    [
        pytest.param(25_000, True, id="above_cap"),
        pytest.param(10_000, False, id="at_cap"),
        pytest.param(0, False, id="empty"),
    ],
)
async def test_collect_search_export_ids_truncation(
    monkeypatch: pytest.MonkeyPatch,
    total: int,
    expected_truncated: bool,  # noqa: FBT001
) -> None:
    """`truncated` is set iff the match set exceeded the result-window cap."""
    n_hits = min(total, SearchService.MAX_RESULT_WINDOW)
    pages = (
        [
            ESSearchResult(
                hits=[ESHit(id=uuid7(), score=1.0) for _ in range(n_hits)],
                total=ESSearchTotal(value=total, relation="eq"),
                page=1,
            )
        ]
        if n_hits
        else []
    )
    scan = MagicMock(side_effect=lambda *_, **__: _aiter(pages))
    monkeypatch.setattr(SearchService, "scan", scan)
    search_export = SearchExport(
        query=SearchQuery(query_string="climate"), sort=["-publication_year"]
    )

    ids, truncated = await _collect_export_ids(_make_service(), search_export)

    assert len(ids) == n_hits
    assert truncated is expected_truncated
    assert scan.call_args.kwargs["sort"] == ["-publication_year"]


async def _aiter(items):
    for item in items:
        yield item


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


async def test_stream_export_file_uses_format_extension_and_path() -> None:
    """The primitive names the file by export id + format, and uses the blob path."""
    reference_service = MagicMock()
    reference_service.stream_references_to_blob = AsyncMock(
        return_value=(BlobStorageFileFactory.build(), 2)
    )
    service = ReferenceExportService.__new__(ReferenceExportService)
    service._reference_service = reference_service  # noqa: SLF001
    service._access_control_service = MagicMock()  # noqa: SLF001
    export_id = uuid7()

    await ReferenceExportService.stream_export_file.__wrapped__(  # type: ignore[attr-defined]
        service,
        export_id=export_id,
        reference_ids=[uuid7(), uuid7()],
        export_format=ExportFormat.RIS,
        blob_repository=MagicMock(),
    )

    kwargs = reference_service.stream_references_to_blob.await_args.kwargs
    assert kwargs["filename"] == f"{export_id}.ris"
    assert kwargs["export_format"] == ExportFormat.RIS
    assert kwargs["path"] == "exports"


async def test_request_reference_export_rejects_unknown_ids() -> None:
    """Unknown reference ids surface the repository's not-found error up front."""
    service = ReferenceExportService.__new__(ReferenceExportService)
    sql_uow = MagicMock()
    sql_uow.references.verify_pk_existence = AsyncMock(
        side_effect=SQLNotFoundError(
            detail="missing",
            lookup_model="Reference",
            lookup_type="id",
            lookup_value={uuid7()},
        )
    )
    service.sql_uow = sql_uow

    with pytest.raises(SQLNotFoundError):
        await ReferenceExportService.request_reference_export.__wrapped__(  # type: ignore[attr-defined]
            service, [uuid7()]
        )
    sql_uow.reference_exports.add.assert_not_called()


async def test_request_reference_export_deduplicates_ids() -> None:
    """Repeated ids collapse (first-seen order) so the stored count matches the file."""
    first, second = uuid7(), uuid7()
    service = ReferenceExportService.__new__(ReferenceExportService)
    sql_uow = MagicMock()
    sql_uow.references.verify_pk_existence = AsyncMock()
    sql_uow.reference_exports.add = AsyncMock()
    service.sql_uow = sql_uow

    reference_export = (
        await ReferenceExportService.request_reference_export.__wrapped__(  # type: ignore[attr-defined]
            service, [first, first, second, first]
        )
    )

    assert reference_export.reference_ids == [first, second]
    sql_uow.references.verify_pk_existence.assert_awaited_once_with([first, second])


def test_reference_export_sql_round_trip() -> None:
    """from_domain → to_domain preserves the reference ids and shared export fields."""
    reference_ids = [uuid7(), uuid7(), uuid7()]
    domain = ReferenceExport(
        reference_ids=reference_ids,
        export_format=ExportFormat.RIS,
        search_export_id=uuid7(),
        chunk_index=3,
    )

    restored = SQLReferenceExport.from_domain(domain).to_domain()

    assert restored.reference_ids == reference_ids
    assert restored.search_export_id == domain.search_export_id
    assert restored.chunk_index == 3
    assert restored.export_format == ExportFormat.RIS
    assert restored.status == domain.status
    assert restored.n_references is None
    assert restored.result_file is None


async def test_run_reference_export_streams_stored_ids_without_search() -> None:
    """run streams the stored reference ids directly."""
    reference_ids = [uuid7(), uuid7()]
    export = ReferenceExport(reference_ids=reference_ids)
    blob = BlobStorageFileFactory.build()

    service = ReferenceExportService.__new__(ReferenceExportService)
    service._claim = AsyncMock(return_value=export)  # type: ignore[method-assign] # noqa: SLF001
    service.stream_export_file = AsyncMock(return_value=(blob, 2))  # type: ignore[method-assign]
    service._complete = AsyncMock()  # type: ignore[method-assign] # noqa: SLF001

    blob_repository = MagicMock()
    await service.run(export.id, blob_repository)

    stream_call = service.stream_export_file.await_args
    assert stream_call is not None
    stream_kwargs = stream_call.kwargs
    assert stream_kwargs["reference_ids"] == reference_ids
    assert stream_kwargs["export_id"] == export.id
    service._complete.assert_awaited_once_with(export.id, blob, 2)  # noqa: SLF001


def _reference_export_service_claiming(export: ReferenceExport):
    service = ReferenceExportService.__new__(ReferenceExportService)
    service._claim = AsyncMock(return_value=export)  # type: ignore[method-assign] # noqa: SLF001
    service.stream_export_file = AsyncMock(  # type: ignore[method-assign]
        return_value=(BlobStorageFileFactory.build(), 0)
    )
    service._complete = AsyncMock()  # type: ignore[method-assign] # noqa: SLF001
    service.fail = AsyncMock()  # type: ignore[method-assign]
    return service


async def test_run_reference_export_prefers_given_ids_even_if_empty() -> None:
    """Ids given to run are streamed instead of stored ids, even an empty list."""
    export = ReferenceExport(reference_ids=[uuid7()])
    service = _reference_export_service_claiming(export)

    await service.run(export.id, MagicMock(), reference_ids=[])

    assert service.stream_export_file.await_args.kwargs["reference_ids"] == []
    service.fail.assert_not_awaited()


async def test_run_reference_export_fails_without_ids() -> None:
    """A chunk run without ids fails rather than exporting nothing."""
    export = ReferenceExport(search_export_id=uuid7(), chunk_index=0)
    service = _reference_export_service_claiming(export)

    await service.run(export.id, MagicMock())

    service.stream_export_file.assert_not_awaited()
    service.fail.assert_awaited_once()


def _chunk(status: ExportStatus, error: str | None = None) -> ReferenceExport:
    return ReferenceExport(
        search_export_id=uuid7(), chunk_index=0, status=status, error=error
    )


@pytest.mark.parametrize(
    ("chunk_statuses", "error", "expected"),
    [
        pytest.param([], None, ExportStatus.PENDING, id="no_chunks"),
        pytest.param([], "boom", ExportStatus.FAILED, id="error"),
        pytest.param(
            [ExportStatus.COMPLETED, ExportStatus.PENDING],
            None,
            ExportStatus.RUNNING,
            id="unfinished",
        ),
        pytest.param(
            [ExportStatus.COMPLETED, ExportStatus.COMPLETED],
            None,
            ExportStatus.COMPLETED,
            id="all_completed",
        ),
        pytest.param(
            [ExportStatus.RUNNING, ExportStatus.FAILED],
            None,
            ExportStatus.FAILED,
            id="chunk_failed",
        ),
    ],
)
def test_search_export_status_is_derived_from_chunks(
    chunk_statuses: list[ExportStatus],
    error: str | None,
    expected: ExportStatus,
) -> None:
    """A search export's status is derived from its error and its chunks."""
    search_export = SearchExport(
        query=SearchQuery(query_string="climate"),
        error=error,
        chunks=[_chunk(status) for status in chunk_statuses],
    )

    assert search_export.status == expected


def _search_export_service(search_export: SearchExport) -> Any:
    service = SearchExportService.__new__(SearchExportService)
    service.get = AsyncMock(return_value=search_export)  # type: ignore[method-assign]
    service._collect_search_export_ids = AsyncMock(  # type: ignore[method-assign] # noqa: SLF001
        return_value=([uuid7(), uuid7()], False)
    )
    service._add_chunk = AsyncMock(  # type: ignore[method-assign] # noqa: SLF001
        return_value=_chunk(ExportStatus.PENDING)
    )
    service.fail = AsyncMock()  # type: ignore[method-assign]
    service._reference_export_service = MagicMock()  # noqa: SLF001
    service._reference_export_service.run = AsyncMock()  # noqa: SLF001
    return service


async def test_run_search_export_runs_single_chunk() -> None:
    """The search's ids are exported as one chunk."""
    search_export = SearchExport(query=SearchQuery(query_string="x"), chunks=[])
    service = _search_export_service(search_export)
    blob_repository = MagicMock()

    await service.run(search_export.id, blob_repository)

    reference_ids, _ = service._collect_search_export_ids.return_value  # noqa: SLF001
    chunk = service._add_chunk.return_value  # noqa: SLF001
    service._reference_export_service.run.assert_awaited_once_with(  # noqa: SLF001
        chunk.id, blob_repository, reference_ids=reference_ids
    )
    service.fail.assert_not_awaited()


async def test_run_search_export_skips_export_with_chunks() -> None:
    """A redelivered task does not redo an export that already has chunks."""
    search_export = SearchExport(
        query=SearchQuery(query_string="x"), chunks=[_chunk(ExportStatus.RUNNING)]
    )
    service = _search_export_service(search_export)

    await service.run(search_export.id, MagicMock())

    service._collect_search_export_ids.assert_not_awaited()  # noqa: SLF001


async def test_run_search_export_fails_on_search_error() -> None:
    """A failure before the chunk runs fails the search export."""
    search_export = SearchExport(query=SearchQuery(query_string="x"), chunks=[])
    service = _search_export_service(search_export)
    service._collect_search_export_ids.side_effect = RuntimeError("kaboom")  # noqa: SLF001

    await service.run(search_export.id, MagicMock())

    service.fail.assert_awaited_once()
    assert "kaboom" in service.fail.await_args.args[1]


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
