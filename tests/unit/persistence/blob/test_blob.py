"""
Unit tests for the blob module (repository, client, models, stream).
"""

import hashlib
import logging
import types
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import AzureBlobConfig
from app.core.exceptions import BlobSizeExceededError, BlobStorageError
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.clients.azure import AzureBlobStorageClient
from app.persistence.blob.models import (
    BlobContainer,
    BlobSignedUrlType,
    BlobStorageFile,
    BlobStorageLocation,
    infer_content_type,
)
from app.persistence.blob.repository import BlobRepository, _BlobClientRegistry
from app.persistence.blob.stream import FileStream


@pytest.mark.asyncio
async def test_upload_file_to_blob_storage():
    repo = BlobRepository()
    content = BytesIO(b"test data")
    dummy_client = DummyClient()
    expected_container = repo._write_backend.containers[BlobContainer.FULL_TEXTS]  # noqa: SLF001
    expected_location = repo._write_backend.location  # noqa: SLF001
    with patch.object(repo, "_preload_config", return_value=dummy_client):
        result = await repo.upload_file_to_blob_storage(
            content=content,
            path="test/path",
            filename="test.txt",
            container=BlobContainer.FULL_TEXTS,
        )
        assert hasattr(dummy_client, "uploaded")
        assert result.filename == "test.txt"
        assert result.container == expected_container
        assert result.location == expected_location


@pytest.mark.asyncio
async def test_stream_file_from_blob_storage():
    repo = BlobRepository()
    file = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="test-container",
        path="test/path",
        filename="test.txt",
    )
    dummy_client = DummyClient()
    with patch.object(repo, "_preload_config", return_value=dummy_client):
        async with repo.stream_file_from_blob_storage(file) as stream:
            lines = [line async for line in stream]
            assert lines == ["dummy"]


@pytest.mark.asyncio
async def test_get_signed_url():
    repo = BlobRepository()
    file = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="test-container",
        path="test/path",
        filename="test.txt",
    )
    dummy_client = DummyClient()
    with patch.object(repo, "_preload_config", return_value=dummy_client):
        url = await repo.get_signed_url(file, BlobSignedUrlType.DOWNLOAD)
        assert str(url) == f"http://signed/{file.filename}/{BlobSignedUrlType.DOWNLOAD}"


@pytest.mark.asyncio
async def test_filestream_stream_and_read_fn():
    async def fake_fn(_dummy):
        return '{"foo": "bar"}\n{"foo": "bar"}\n{"foo": "bar"}'

    fs = FileStream(
        fn=fake_fn,
        fn_kwargs=[{"_dummy": "value"}, {"_dummy": "value"}, {"_dummy": "value"}],
    )
    # Test read (implicitly tests stream also)
    result = await fs.read()
    assert b'{"foo": "bar"}\n{"foo": "bar"}\n{"foo": "bar"}' in result.getvalue()


@pytest.mark.asyncio
async def test_filestream_stream_and_read_gen():
    async def fake_gen():
        yield '{"foo": "bar"}'
        yield '{"foo": "bar2"}'

    fs = FileStream(
        generator=fake_gen(),
    )
    # Test read (implicitly tests stream also)
    result = await fs.read()
    assert b'{"foo": "bar"}\n{"foo": "bar2"}' in result.getvalue()


@pytest.mark.parametrize(
    ("filename", "expected_content_type"),
    [
        ("file.jsonl", "application/jsonl"),
        ("file.json", "application/json"),
        ("file.csv", "text/csv"),
        ("file.txt", "text/plain"),
        ("paper.pdf", "application/pdf"),
        ("feed.xml", "application/xml"),
        ("page.html", "text/html"),
        ("file.unknown", "application/octet-stream"),
        ("noextension", "application/octet-stream"),
        ("MIXED.Pdf", "application/pdf"),
    ],
)
def test_infer_content_type(filename, expected_content_type):
    assert infer_content_type(filename) == expected_content_type


@pytest.mark.asyncio
async def test_blobstoragefile_to_uri_and_from_uri():
    file = BlobStorageFile(
        location=BlobStorageLocation.AZURE,
        container="cont",
        path="some/path",
        filename="file.txt",
    )
    uri = file.to_uri()
    assert uri == "azure://cont/some/path/file.txt"
    new_file = BlobStorageFile.from_uri(uri)
    assert new_file.location == "azure"
    assert new_file.container == "cont"
    assert new_file.path == "some/path"
    assert new_file.filename == "file.txt"


@pytest.mark.asyncio
async def test_blobstoragefile_coerces_from_uri_string():
    """Pydantic validation accepts the URI string form transparently."""
    uri = "azure://cont/some/path/file.txt"
    file = BlobStorageFile.model_validate(uri)
    assert file.location == "azure"
    assert file.filename == "file.txt"


@pytest.mark.asyncio
async def test_blobstoragefile_serializes_to_uri_in_json_mode():
    file = BlobStorageFile(
        location=BlobStorageLocation.AZURE,
        container="cont",
        path="some/path",
        filename="file.txt",
    )
    assert file.model_dump(mode="json") == "azure://cont/some/path/file.txt"


@pytest.mark.parametrize(
    ("uri", "expected_location"),
    [
        (
            "https://example.com/papers/2024/paper.pdf",
            BlobStorageLocation.HTTPS,
        ),
        (
            "http://host.docker.internal:8080/papers/foo.pdf",
            BlobStorageLocation.HTTP,
        ),
    ],
)
def test_blobstoragefile_remote_uri_round_trip(uri, expected_location):
    """Remote blobs round-trip via http(s) URIs, preserving the scheme."""
    file = BlobStorageFile.from_uri(uri)
    assert file.location == expected_location
    assert file.is_remote
    assert file.to_uri() == uri


def test_blobstoragefile_remote_coerces_from_url_string():
    """Pydantic validation accepts an https URL transparently as a remote blob."""
    file = BlobStorageFile.model_validate("https://example.com/papers/foo.pdf")
    assert file.is_remote
    assert file.location == BlobStorageLocation.HTTPS
    assert file.filename == "foo.pdf"


def test_from_uri_rejects_unknown_scheme():
    with pytest.raises(BlobStorageError):
        BlobStorageFile.from_uri("ftp://example.com/foo.pdf")


def test_from_uri_rejects_malformed():
    with pytest.raises(BlobStorageError):
        BlobStorageFile.from_uri("azure://only-two-parts")


class _RecordingClient(GenericBlobStorageClient):
    """Test double: stream_chunks yields canned bytes; upload_file records input."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self._chunks = chunks or []
        self.uploaded_chunks: list[bytes] = []
        self.uploaded_to: BlobStorageFile | None = None

    async def upload_file(self, content, file, content_type=None):  # type: ignore[no-untyped-def]
        # `copy` passes an async iterator of bytes
        del content_type
        async for chunk in content:
            self.uploaded_chunks.append(chunk)
        self.uploaded_to = file

    async def stream_chunks(self, file):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk

    async def generate_signed_url(self, file, interaction_type, content_disposition):
        return "http://unused"


@pytest.mark.asyncio
async def test_copy_streams_through_and_computes_sha256_and_size():
    """copy() tees source chunks through sha256+size to the destination upload."""

    payload_chunks = [b"%PDF-1.7\n", b"hello world\n", b"\x00\x01\x02\x03"]
    payload = b"".join(payload_chunks)
    expected_sha = hashlib.sha256(payload).hexdigest()

    source = BlobStorageFile.from_uri("https://example.com/papers/foo.pdf")
    destination = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="full-texts",
        path="2026/05",
        filename="foo.pdf",
    )

    src_client = _RecordingClient(chunks=payload_chunks)
    dest_client = _RecordingClient()

    repo = BlobRepository()
    with patch.object(
        repo,
        "_preload_config",
        side_effect=lambda f: src_client if f is source else dest_client,
    ):
        result = await repo.copy(source, destination)

    assert dest_client.uploaded_to == destination
    assert b"".join(dest_client.uploaded_chunks) == payload
    assert result.byte_size == len(payload)
    assert result.sha256_checksum == expected_sha
    assert result.source == source
    assert result.destination == destination


@pytest.mark.asyncio
async def test_copy_empty_source_yields_known_sha256():
    """Empty source still produces a valid result (sha256 of empty string)."""

    source = BlobStorageFile.from_uri("https://example.com/empty.pdf")
    destination = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="full-texts",
        path="p",
        filename="empty.pdf",
    )
    src_client = _RecordingClient(chunks=[])
    dest_client = _RecordingClient()

    repo = BlobRepository()
    with patch.object(
        repo,
        "_preload_config",
        side_effect=lambda f: src_client if f is source else dest_client,
    ):
        result = await repo.copy(source, destination)

    assert result.byte_size == 0
    assert result.sha256_checksum == hashlib.sha256(b"").hexdigest()
    assert dest_client.uploaded_chunks == []


@pytest.mark.asyncio
async def test_copy_aborts_when_max_bytes_exceeded():
    """Cumulative chunk size strictly above max_bytes aborts the stream."""

    source = BlobStorageFile.from_uri("https://example.com/big.pdf")
    destination = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="full-texts",
        path="p",
        filename="big.pdf",
    )
    src_client = _RecordingClient(chunks=[b"a" * 100, b"b" * 100])
    dest_client = _RecordingClient()

    repo = BlobRepository()
    with (
        patch.object(
            repo,
            "_preload_config",
            side_effect=lambda f: src_client if f is source else dest_client,
        ),
        pytest.raises(BlobSizeExceededError, match="max_bytes=150"),
    ):
        await repo.copy(source, destination, max_bytes=150)


@pytest.mark.asyncio
async def test_copy_max_bytes_none_disables_check():
    """A None max_bytes does not enforce any cap."""

    source = BlobStorageFile.from_uri("https://example.com/foo.pdf")
    destination = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="full-texts",
        path="p",
        filename="foo.pdf",
    )
    src_client = _RecordingClient(chunks=[b"x" * 100_000])
    dest_client = _RecordingClient()

    repo = BlobRepository()
    with patch.object(
        repo,
        "_preload_config",
        side_effect=lambda f: src_client if f is source else dest_client,
    ):
        result = await repo.copy(source, destination, max_bytes=None)

    assert result.byte_size == 100_000


@pytest.mark.asyncio
async def test_copy_rejects_destination_on_other_backend():
    """A destination not on the active write backend should be refused."""
    source = BlobStorageFile.from_uri("https://example.com/foo.pdf")
    destination = BlobStorageFile(
        location=BlobStorageLocation.AZURE,
        container="cont",
        path="p",
        filename="foo.pdf",
    )

    repo = BlobRepository()
    assert repo._write_backend.location == BlobStorageLocation.MINIO  # noqa: SLF001
    with pytest.raises(BlobStorageError):
        await repo.copy(source, destination)


_STREAM_FILE = BlobStorageFile(
    location=BlobStorageLocation.MINIO,
    container="c",
    path="p",
    filename="f.txt",
)


@pytest.mark.asyncio
async def test_stream_file_reassembles_multibyte_char_split_across_chunks():
    """A UTF-8 char split across chunk boundaries must not raise or corrupt."""
    # "café" -> b"caf\xc3\xa9"; split mid-way through the two-byte é.
    client = _RecordingClient(chunks=[b"caf\xc3", b"\xa9\n"])
    lines = [line async for line in client.stream_file(_STREAM_FILE)]
    assert lines == ["café"]


@pytest.mark.asyncio
async def test_stream_file_splits_lines_across_chunks():
    """Lines spanning chunk boundaries are reassembled; trailing line emitted."""
    client = _RecordingClient(chunks=[b"one\ntw", b"o\nthree"])
    lines = [line async for line in client.stream_file(_STREAM_FILE)]
    assert lines == ["one", "two", "three"]


class DummyClient(GenericBlobStorageClient):
    async def upload_file(self, content, file, content_type=None):
        self.uploaded = (content, file, content_type)

    async def stream_chunks(self, file):
        yield b"dummy"

    async def generate_signed_url(
        self, file, interaction_type, content_disposition=None
    ):
        return f"http://signed/{file.filename}/{interaction_type}"


@pytest.mark.asyncio
async def test_generic_blob_storage_client_interface():
    client = DummyClient()
    # upload_file
    await client.upload_file("content", "file")
    assert hasattr(client, "uploaded")
    # stream_file
    gen = client.stream_file("file")
    assert isinstance(gen, types.AsyncGeneratorType)
    # generate_signed_url
    url = await client.generate_signed_url(
        BlobStorageFile(
            location=BlobStorageLocation.AZURE,
            container="c",
            path="p",
            filename="f.txt",
        ),
        BlobSignedUrlType.DOWNLOAD,
        None,
    )
    assert url.startswith("http://signed/")


class _CloseRecordingClient(GenericBlobStorageClient):
    """Test double tracking aclose() calls; raises on demand."""

    def __init__(self, *, raise_on_close: bool = False) -> None:
        self.aclose_calls = 0
        self._raise = raise_on_close

    async def upload_file(self, content, file, content_type=None):
        return None

    async def stream_chunks(self, file):
        yield b""

    async def generate_signed_url(self, file, interaction_type, content_disposition):
        return "http://unused"

    async def aclose(self) -> None:
        self.aclose_calls += 1
        if self._raise:
            msg = "boom"
            raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_blob_registry_get_reuses_client_per_location():
    """Repeated get()s for one location instantiate once; distinct per location."""
    registry = _BlobClientRegistry()
    minio_file_a = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="c",
        path="p",
        filename="a.txt",
    )
    minio_file_b = BlobStorageFile(
        location=BlobStorageLocation.MINIO,
        container="c",
        path="p",
        filename="b.txt",
    )
    https_file = BlobStorageFile.from_uri("https://example.com/foo.pdf")

    # Fresh client per call so identity-equality (first is second) can only hold
    # if get() returned the cached instance instead of calling _instantiate again.
    instantiate_count: dict[BlobStorageLocation, int] = {}

    def fake_instantiate(file: BlobStorageFile) -> GenericBlobStorageClient:
        instantiate_count[file.location] = instantiate_count.get(file.location, 0) + 1
        return _CloseRecordingClient()

    with patch.object(
        _BlobClientRegistry, "_instantiate", side_effect=fake_instantiate
    ):
        first = await registry.get(minio_file_a)
        second = await registry.get(minio_file_b)
        remote = await registry.get(https_file)

    assert first is second  # cached: same instance for two MINIO gets
    assert first is not remote  # distinct backend, distinct instance
    assert instantiate_count == {
        BlobStorageLocation.MINIO: 1,
        BlobStorageLocation.HTTPS: 1,
    }


@pytest.mark.asyncio
async def test_blob_registry_aclose_closes_each_and_clears(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """aclose() invokes aclose on every held client, clears the dict, logs failures."""
    registry = _BlobClientRegistry()
    good = _CloseRecordingClient()
    bad = _CloseRecordingClient(raise_on_close=True)
    registry._clients[BlobStorageLocation.MINIO] = good  # noqa: SLF001
    registry._clients[BlobStorageLocation.HTTPS] = bad  # noqa: SLF001

    with caplog.at_level(logging.WARNING, logger="app.persistence.blob.repository"):
        await registry.aclose()

    assert good.aclose_calls == 1
    assert bad.aclose_calls == 1
    assert registry._clients == {}  # noqa: SLF001
    # The raising client's failure was logged, not propagated.
    assert any(
        "Error closing blob client" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_azure_blob_client_aclose_closes_service_client_and_credential():
    """aclose() closes both BlobServiceClient and managed-identity credential."""
    config = AzureBlobConfig(
        storage_account_name="acct",
        # credential=None -> uses_managed_identity == True
        containers={c: "test" for c in BlobContainer},
    )
    assert config.uses_managed_identity

    fake_credential = AsyncMock()
    fake_service_client = AsyncMock()

    with (
        patch(
            "app.persistence.blob.clients.azure.DefaultAzureCredential",
            return_value=fake_credential,
        ),
        patch(
            "app.persistence.blob.clients.azure.BlobServiceClient",
            return_value=fake_service_client,
        ),
    ):
        client = AzureBlobStorageClient(config, presigned_url_expiry_seconds=60)
        await client.aclose()

    fake_service_client.close.assert_awaited_once()
    fake_credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_azure_blob_client_aclose_no_credential_when_using_account_key():
    """With an account key (no managed identity), only the service client is closed."""
    config = AzureBlobConfig(
        storage_account_name="acct",
        credential="account-key",
        containers={c: "test" for c in BlobContainer},
    )
    assert not config.uses_managed_identity

    fake_service_client = AsyncMock()

    with (
        patch(
            "app.persistence.blob.clients.azure.DefaultAzureCredential"
        ) as default_credential_cls,
        patch(
            "app.persistence.blob.clients.azure.BlobServiceClient",
            return_value=fake_service_client,
        ),
    ):
        client = AzureBlobStorageClient(config, presigned_url_expiry_seconds=60)
        await client.aclose()

    default_credential_cls.assert_not_called()
    fake_service_client.close.assert_awaited_once()
    assert client._aio_credential is None  # noqa: SLF001
