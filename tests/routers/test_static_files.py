"""Test static file serving directory."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.api.root import mount_static_files


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application instance for testing."""
    return FastAPI(title="Test Static Files")


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """Create a test client for the FastAPI application."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def static_file(
    static_file_mount: Path,
) -> AsyncGenerator[tuple[Path, str], None]:
    """Set up a static file for testing."""
    test_file_path = static_file_mount / "test-file.json"
    content = '{"test": "data"}'
    test_file_path.write_text(content)
    yield test_file_path.relative_to(static_file_mount), content
    test_file_path.unlink()


@pytest.fixture(autouse=True)
async def static_file_mount(app: FastAPI) -> AsyncGenerator[Path, None]:
    """Mount the static files for testing."""
    static_file_path = Path(".test.tmp")
    static_file_path.mkdir(exist_ok=True, parents=True)
    mount_static_files(app, static_dir=static_file_path)
    yield static_file_path
    static_file_path.rmdir()


async def test_static_serve_happy_path(
    client: AsyncClient, static_file: tuple[Path, str]
) -> None:
    """Test the happy path of retrieving a static file."""
    response = await client.get(f"/v1/static/{static_file[0]}")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "application/json"
    assert response.text == static_file[1]


@pytest.mark.parametrize(
    "file_path",
    [
        # Missing
        "",
        "/nonexistent/file.json",
        "123456",
        "test-dir",
        # Malicious
        "../main.py",
        "../../../../../../etc/passwd",
        "/etc/passwd",
        "taxonomies/../../main.py",
        "%2e%2e/main.py",
        "%252e%252e/main.py",
        "..\\main.py",
    ],
)
async def test_missing_file_paths(client: AsyncClient, file_path: str) -> None:
    """Test various missing file paths."""
    response = await client.get(f"/v1/static/{file_path}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Not Found"}
