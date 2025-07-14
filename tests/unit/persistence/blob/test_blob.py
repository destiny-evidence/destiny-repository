"""
Unit tests for the blob module (repository, client, models, stream).
"""

import types
from io import BytesIO
from unittest.mock import patch

import pytest

from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import (
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
    with patch.object(repo, "_preload_config", return_value=dummy_client):
        result = await repo.upload_file_to_blob_storage(
            content=content,
            path="test/path",
            filename="test.txt",
            container="test-container",
            location=BlobStorageLocation.MINIO,
        )
        assert hasattr(dummy_client, "uploaded")
        assert result.filename == "test.txt"
        assert result.container == "test-container"


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
        return "dummy"

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
        yield "dummy1"
        yield "dummy2"

    fs = FileStream(
        generator=fake_gen(),
    )
    # Test read (implicitly tests stream also)
    result = await fs.read()
    assert b'{"foo": "bar"}\n{"foo": "bar"}' in result.getvalue()


@pytest.mark.parametrize(
    ("location", "container", "path", "filename", "expected_content_type"),
    [
        (BlobStorageLocation.AZURE, "cont", "p", "file.jsonl", "application/jsonl"),
        (BlobStorageLocation.MINIO, "cont", "p", "file.json", "application/json"),
        (BlobStorageLocation.AZURE, "cont", "p", "file.csv", "text/csv"),
        (BlobStorageLocation.MINIO, "cont", "p", "file.txt", "text/plain"),
        (
            BlobStorageLocation.AZURE,
            "cont",
            "p",
            "file.unknown",
            "application/octet-stream",
        ),
    ],
)
def test_blobstoragefile_content_type(
    location, container, path, filename, expected_content_type
):
    file = BlobStorageFile(
        location=location,
        container=container,
        path=path,
        filename=filename,
    )
    ct = file.content_type
    assert ct == expected_content_type


@pytest.mark.asyncio
async def test_blobstoragefile_to_sql_and_from_sql():
    file = BlobStorageFile(
        location=BlobStorageLocation.AZURE,
        container="cont",
        path="some/path",
        filename="file.txt",
    )
    sql = await file.to_sql()
    assert sql == "azure://cont/some/path/file.txt"
    new_file = await BlobStorageFile.from_sql(sql)
    assert new_file.location == "azure"
    assert new_file.container == "cont"
    assert new_file.path == "some/path"
    assert new_file.filename == "file.txt"


class DummyClient(GenericBlobStorageClient):
    async def upload_file(self, content, file):
        self.uploaded = (content, file)

    async def stream_file(self, file):
        yield "dummy"

    async def generate_signed_url(self, file, interaction_type):
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
