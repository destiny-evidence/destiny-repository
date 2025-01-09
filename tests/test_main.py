"""Test the main module."""

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"message": "Hello World"}
