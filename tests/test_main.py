"""Test the main module."""

from fastapi.status import HTTP_200_OK
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"message": "Hello World"}
