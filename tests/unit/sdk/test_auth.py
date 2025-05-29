"""Tests for HMAC Authentication."""

from collections.abc import AsyncGenerator

import destiny_sdk
import pytest
from fastapi import APIRouter, Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient

TEST_SECRET_KEY = "dlfskdfhgk8ei346oiehslkdfrerikfglser934utofs"


@pytest.fixture
def hmac_app() -> FastAPI:
    """
    Create a FastAPI application instance for testing HMAC authentication.

    Returns:
        FastAPI: FastAPI app with test router configured with HMAC auth.

    """
    app = FastAPI(title="Test HMAC Auth")
    auth = destiny_sdk.auth.HMACAuth(secret_key=TEST_SECRET_KEY)

    def __endpoint() -> dict:
        return {"message": "ok"}

    router = APIRouter(prefix="/test", dependencies=[Depends(auth)])
    router.add_api_route(
        path="/hmac/",
        methods=["POST"],
        status_code=status.HTTP_200_OK,
        endpoint=__endpoint,
    )

    app.include_router(router)
    return app


@pytest.fixture
async def client(hmac_app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """
    Create a test client for the FastAPI application.

    Args:
        app (FastAPI): FastAPI application instance.

    Returns:
        TestClient: Test client for the FastAPI application.

    """
    async with AsyncClient(
        transport=ASGITransport(app=hmac_app),
        base_url="http://test",
    ) as client:
        yield client


async def test_hmac_authentication_happy_path(client: AsyncClient):
    """Test authentication is successful when signature is correct."""
    request_body = '{"message": "info"}'
    auth = destiny_sdk.client.HMACSigningAuth(secret_key=TEST_SECRET_KEY)

    response = await client.post("test/hmac/", content=request_body, auth=auth)

    assert response.status_code == status.HTTP_200_OK


async def test_hmac_authentication_incorrect_signature(client: AsyncClient):
    """Test authentication fails when the signature does not match."""
    response = await client.post(
        "test/hmac/", headers={"Authorization": "Signature nonsense-signature"}, json={}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid" in response.json()["detail"]


async def test_hmac_authentication_no_signature(client: AsyncClient):
    """Test authentication fails if the signature is not included."""
    response = await client.post("test/hmac/", json={})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "header missing" in response.json()["detail"]


async def test_hmac_authentication_wrong_auth_type(client: AsyncClient):
    """Test authentication fails if the signature is not included."""
    response = await client.post(
        "test/hmac/", json={}, headers={"Authorization": "Bearer nonsense-token"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "type not supported" in response.json()["detail"]
