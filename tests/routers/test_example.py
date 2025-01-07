import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import example


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(example.router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_example_index(client):
    response = client.get("/examples")
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_get_example(client):
    response = client.get("/examples/foo")
    assert response.status_code == 200
    assert response.json()["id"] == "foo"


def test_get_missing_example(client):
    response = client.get("/examples/missing")
    assert response.status_code == 404
