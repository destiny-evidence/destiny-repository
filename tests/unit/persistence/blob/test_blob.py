"""
Unit tests for the blob module (repository, client, models, stream).
"""

import hashlib
import types
from io import BytesIO
from unittest.mock import patch

import pytest

from app.core.exceptions import BlobSizeExceededError, BlobStorageError
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import (
    BlobContainer,
    BlobSignedUrlType,
    BlobStorageFile,
    BlobStorageLocation,
)
from app.persistence.blob.repository import BlobRepository
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
    ("location", "container", "path", "filename", "expected_content_type"),
    [
        (BlobStorageLocation.AZURE, "cont", "p", "file.jsonl", "application/jsonl"),
        (BlobStorageLocation.MINIO, "cont", "p", "file.json", "application/json"),
        (BlobStorageLocation.AZURE, "cont", "p", "file.csv", "text/csv"),
        (BlobStorageLocation.MINIO, "cont", "p", "file.txt", "text/plain"),
        (BlobStorageLocation.AZURE, "cont", "p", "paper.pdf", "application/pdf"),
        (BlobStorageLocation.AZURE, "cont", "p", "feed.xml", "application/xml"),
        (BlobStorageLocation.AZURE, "cont", "p", "page.html", "text/html"),
        (
            BlobStorageLocation.AZURE,
            "cont",
            "p",
            "file.unknown",
            "application/octet-stream",
        ),
    ],
)
def test_blobstoragefile_content_type_inferred(
    location, container, path, filename, expected_content_type
):
    file = BlobStorageFile(
        location=location,
        container=container,
        path=path,
        filename=filename,
    )
    assert file.content_type == expected_content_type


def test_blobstoragefile_content_type_explicit_overrides_extension():
    """An explicit content_type wins over extension-based inference."""
    file = BlobStorageFile(
        location=BlobStorageLocation.AZURE,
        container="cont",
        path="p",
        filename="paper.pdf",
        content_type="application/x-custom",
    )
    assert file.content_type == "application/x-custom"


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


def test_blobstoragefile_remote_content_type_inferred_from_extension():
    file = BlobStorageFile.from_uri("https://example.com/papers/foo.pdf")
    assert file.content_type == "application/pdf"


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

    async def upload_file(self, content, file):  # type: ignore[no-untyped-def]
        # `copy` passes an async iterator of bytes
        async for chunk in content:
            self.uploaded_chunks.append(chunk)
        self.uploaded_to = file

    async def stream_chunks(self, file):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk

    async def generate_signed_url(self, file, interaction_type):
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


class DummyClient(GenericBlobStorageClient):
    async def upload_file(self, content, file):
        self.uploaded = (content, file)

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
    )
    assert url.startswith("http://signed/")
