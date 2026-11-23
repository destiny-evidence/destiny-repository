"""Unit tests for the search-export lifecycle service and reference streaming."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.domain.references.services import export_service
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.export_service import (
    ReferenceExportService,
    SearchExportService,
)
from app.persistence.es.persistence import ESHit, ESSearchResult, ESSearchTotal
from app.persistence.es.repository import ES_MAX_PAGE_SIZE
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    BlobStorageFileFactory,
    EnhancementFactory,
    ReferenceFactory,
)

# Unwrapped from their UoW so tests can drive them with mocks.
_collect = SearchExportService._collect.__wrapped__  # type: ignore[attr-defined]  # noqa: SLF001
_distribute = SearchExportService._distribute.__wrapped__  # type: ignore[attr-defined]  # noqa: SLF001


def _page(n_hits: int, total: int) -> ESSearchResult:
    return ESSearchResult(
        hits=[ESHit(id=uuid7(), score=1.0) for _ in range(n_hits)],
        total=ESSearchTotal(value=total, relation="eq"),
        page=1,
    )


def _scanning_service(monkeypatch: pytest.MonkeyPatch, *pages: ESSearchResult) -> Any:
    """A service whose scan yields ``pages``, with chunks of 2."""
    monkeypatch.setattr(export_service.settings, "search_export_chunk_size", 2)
    service = SearchExportService.__new__(SearchExportService)
    service._search_service = MagicMock()  # noqa: SLF001
    service._search_service.scan = MagicMock(side_effect=lambda *_, **__: _aiter(pages))  # noqa: SLF001
    service._add_chunks = AsyncMock(  # type: ignore[method-assign] # noqa: SLF001
        side_effect=lambda export, chunk_sizes: [
            ReferenceExport(search_export_id=export.id, chunk_index=chunk_index)
            for chunk_index in range(len(chunk_sizes))
        ]
    )
    service._dispatch = AsyncMock()  # type: ignore[method-assign] # noqa: SLF001
    return service


async def test_collect_returns_one_chunk_of_every_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single file export is one chunk sized to every matching id."""
    pages = (_page(2, total=3), _page(1, total=3))
    service = _scanning_service(monkeypatch, *pages)
    search_export = SearchExport(
        query=SearchQuery(query_string="climate"), sort=["-publication_year"]
    )

    chunk, reference_ids = await _collect(service, search_export)

    assert reference_ids == [hit.id for page in pages for hit in page.hits]
    service._add_chunks.assert_awaited_once_with(search_export, [3])  # noqa: SLF001
    assert chunk.chunk_index == 0
    scan_kwargs = service._search_service.scan.call_args.kwargs  # noqa: SLF001
    assert scan_kwargs["sort"] == ["-publication_year"]
    assert scan_kwargs["page_size"] == ES_MAX_PAGE_SIZE


async def test_collect_returns_empty_chunk_without_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search with no matches is still one (empty) chunk."""
    service = _scanning_service(monkeypatch)
    search_export = SearchExport(query=SearchQuery(query_string="climate"))

    _, reference_ids = await _collect(service, search_export)

    assert reference_ids == []
    service._add_chunks.assert_awaited_once_with(search_export, [0])  # noqa: SLF001


async def test_collect_reuses_an_existing_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rerun single file export reuses its chunk rather than adding another."""
    service = _scanning_service(monkeypatch, _page(1, total=1))
    chunk = _chunk(ExportStatus.RUNNING)
    search_export = SearchExport(
        query=SearchQuery(query_string="climate"), chunks=[chunk]
    )

    collected, _ = await _collect(service, search_export)

    assert collected is chunk
    service._add_chunks.assert_not_awaited()  # noqa: SLF001


async def test_distribute_dispatches_a_chunk_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chunks are allocated from the scan's total and each page dispatched."""
    pages = (_page(2, total=5), _page(2, total=5), _page(1, total=5))
    service = _scanning_service(monkeypatch, *pages)
    search_export = SearchExport(query=SearchQuery(query_string="climate"))

    await _distribute(service, search_export)

    service._add_chunks.assert_awaited_once_with(search_export, [2, 2, 1])  # noqa: SLF001
    scan_kwargs = service._search_service.scan.call_args.kwargs  # noqa: SLF001
    assert scan_kwargs["page_size"] == 2
    assert [
        (call.args[0].chunk_index, call.args[1])
        for call in service._dispatch.await_args_list  # noqa: SLF001
    ] == [(chunk_index, page.hits) for chunk_index, page in enumerate(pages)]


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

    await reference_service.stream_references_to_blob(
        reference_ids=[reference.id],
        export_format=export_format,
        access_control_service=_identity_access_control(),
        blob_repository=blob_repository,
        path="search_exports",
        filename=f"{reference.id}.{export_format.extension}",
        chunk_size=100,
    )
    body = b"".join([chunk async for chunk in captured["content"].stream()]).decode()
    return body, captured["filename"]


async def test_stream_references_to_blob_serializes_ris() -> None:
    """A RIS export streams a rendered RIS record per reference."""
    reference = _reference_with_title("A Title")
    reference_service = _reference_service_with([reference], AsyncMock())

    body, filename = await _capture_uploaded_body(
        reference_service, ExportFormat.RIS, reference
    )

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

    body, filename = await _capture_uploaded_body(
        reference_service, ExportFormat.JSONL, reference
    )

    assert filename.endswith(".jsonl")
    assert body.strip() == '{"id": "x"}'
    anti_corruption.reference_to_sdk.assert_awaited_once_with(reference)


async def test_stream_export_file_uses_format_extension_and_path() -> None:
    """The primitive names the file by export id + format, and uses the blob path."""
    reference_service = MagicMock()
    reference_service.stream_references_to_blob = AsyncMock(
        return_value=BlobStorageFileFactory.build()
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
    assert reference_export.n_references == 2
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
    service.stream_export_file = AsyncMock(return_value=blob)  # type: ignore[method-assign]
    service._complete = AsyncMock()  # type: ignore[method-assign] # noqa: SLF001

    blob_repository = MagicMock()
    await service.run(export.id, blob_repository)

    stream_call = service.stream_export_file.await_args
    assert stream_call is not None
    stream_kwargs = stream_call.kwargs
    assert stream_kwargs["reference_ids"] == reference_ids
    assert stream_kwargs["export_id"] == export.id
    service._complete.assert_awaited_once_with(export.id, blob)  # noqa: SLF001


def _reference_export_service_claiming(export: ReferenceExport):
    service = ReferenceExportService.__new__(ReferenceExportService)
    service._claim = AsyncMock(return_value=export)  # type: ignore[method-assign] # noqa: SLF001
    service.stream_export_file = AsyncMock(  # type: ignore[method-assign]
        return_value=BlobStorageFileFactory.build()
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


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(ExportStatus.RUNNING, ExportStatus.FAILED, id="running"),
        pytest.param(ExportStatus.COMPLETED, ExportStatus.COMPLETED, id="completed"),
    ],
)
async def test_fail_reference_export_leaves_finished_exports(
    session: AsyncSession, status: ExportStatus, expected: ExportStatus
) -> None:
    """A late failure can't overwrite an export that has since finished."""
    export = SQLReferenceExport(reference_ids=[uuid7()], status=status)
    session.add(export)
    await session.commit()
    service = ReferenceExportService(
        MagicMock(), AsyncSqlUnitOfWork(session), MagicMock(), MagicMock(), MagicMock()
    )

    failed = await service.fail(export.id, "late")

    assert failed.status == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(ExportStatus.RUNNING, ExportStatus.COMPLETED, id="running"),
        pytest.param(ExportStatus.FAILED, ExportStatus.FAILED, id="failed"),
    ],
)
async def test_complete_reference_export_leaves_finished_exports(
    session: AsyncSession, status: ExportStatus, expected: ExportStatus
) -> None:
    """A late completion can't revive an export that has since failed."""
    export = SQLReferenceExport(reference_ids=[uuid7()], status=status)
    session.add(export)
    await session.commit()
    service = ReferenceExportService(
        MagicMock(), AsyncSqlUnitOfWork(session), MagicMock(), MagicMock(), MagicMock()
    )

    completed = await service._complete(  # noqa: SLF001
        export.id, BlobStorageFileFactory.build()
    )

    assert completed.status == expected


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
    service._collect = AsyncMock(  # type: ignore[method-assign] # noqa: SLF001
        return_value=(_chunk(ExportStatus.PENDING), [uuid7(), uuid7()])
    )
    service._distribute = AsyncMock()  # type: ignore[method-assign] # noqa: SLF001
    service.fail = AsyncMock()  # type: ignore[method-assign]
    service._reference_export_service = MagicMock()  # noqa: SLF001
    service._reference_export_service.run = AsyncMock()  # noqa: SLF001
    return service


@pytest.mark.parametrize(
    "chunks",
    [
        pytest.param([], id="fresh"),
        pytest.param([_chunk(ExportStatus.RUNNING)], id="redelivered"),
    ],
)
async def test_run_search_export_runs_single_file_inline(
    chunks: list[ReferenceExport],
) -> None:
    """An export requested within the single file size runs as one chunk, inline."""
    search_export = SearchExport(
        query=SearchQuery(query_string="x"),
        n_references=export_service.settings.max_single_file_search_export_size,
        chunks=chunks,
    )
    service = _search_export_service(search_export)
    blob_repository = MagicMock()

    await service.run(search_export.id, blob_repository)

    chunk, reference_ids = service._collect.return_value  # noqa: SLF001
    service._reference_export_service.run.assert_awaited_once_with(  # noqa: SLF001
        chunk.id, blob_repository, reference_ids=reference_ids
    )
    service._distribute.assert_not_awaited()  # noqa: SLF001
    service.fail.assert_not_awaited()


async def test_run_search_export_distributes_beyond_single_file_size() -> None:
    """An export requested beyond the single file size is left to chunk tasks."""
    search_export = SearchExport(
        query=SearchQuery(query_string="x"),
        n_references=export_service.settings.max_single_file_search_export_size + 1,
        chunks=[],
    )
    service = _search_export_service(search_export)

    await service.run(search_export.id, MagicMock())

    service._distribute.assert_awaited_once_with(search_export)  # noqa: SLF001
    service._collect.assert_not_awaited()  # noqa: SLF001
    service._reference_export_service.run.assert_not_awaited()  # noqa: SLF001
    service.fail.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "chunks"),
    [
        pytest.param("boom", [], id="failed"),
        pytest.param(None, [_chunk(ExportStatus.COMPLETED)], id="completed"),
    ],
)
async def test_run_search_export_skips_finished_export(
    error: str | None, chunks: list[ReferenceExport]
) -> None:
    """A redelivered task leaves a finished export alone."""
    search_export = SearchExport(
        query=SearchQuery(query_string="x"), error=error, chunks=chunks
    )
    service = _search_export_service(search_export)

    await service.run(search_export.id, MagicMock())

    service._collect.assert_not_awaited()  # noqa: SLF001
    service._distribute.assert_not_awaited()  # noqa: SLF001
    service.fail.assert_not_awaited()


async def test_run_search_export_fails_interrupted_distribution() -> None:
    """A redelivered chunked export can't safely resume, so it fails."""
    search_export = SearchExport(
        query=SearchQuery(query_string="x"),
        n_references=export_service.settings.max_single_file_search_export_size + 1,
        chunks=[_chunk(ExportStatus.COMPLETED), _chunk(ExportStatus.PENDING)],
    )
    service = _search_export_service(search_export)

    await service.run(search_export.id, MagicMock())

    service._distribute.assert_not_awaited()  # noqa: SLF001
    service.fail.assert_awaited_once_with(
        search_export.id, "Export was interrupted, please retry."
    )


async def test_run_search_export_fails_on_search_error() -> None:
    """A failure before the chunk runs fails the search export."""
    search_export = SearchExport(query=SearchQuery(query_string="x"), chunks=[])
    service = _search_export_service(search_export)
    service._collect.side_effect = RuntimeError("kaboom")  # noqa: SLF001

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

    body, _ = await _capture_uploaded_body(
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
