"""Defines tests for the example router."""

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.routers import example


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI()
    app.include_router(example.router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """
    Create a test client for the FastAPI application.

    Args:
        app (FastAPI): FastAPI application instance.

    Returns:
        TestClient: Test client for the FastAPI application.

    """
    return TestClient(app)


def test_example_index(client: TestClient) -> None:
    """
    Test the index returned by the example router.

    Args:
        client (TestClient): Test client for the FastAPI application.

    """
    response = client.get("/examples")
    expected_response_length = 3
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == expected_response_length


def test_get_example(client: TestClient) -> None:
    """
    Test the retrieval of a specific example.

    Args:
        client (TestClient): Test client for the FastAPI application.

    """
    response = client.get("/examples/foo")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == "foo"


def test_get_missing_example(client: TestClient) -> None:
    """
    Test the retrieval of a missing example.

    Args:
        client (TestClient): Test client for the FastAPI application.

    """
    response = client.get("/examples/missing")
    assert response.status_code == status.HTTP_404_NOT_FOUND
