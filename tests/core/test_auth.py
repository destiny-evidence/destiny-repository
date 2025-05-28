"""Tests for HMAC Authentication."""

import hashlib
import hmac
from collections.abc import AsyncGenerator

import pytest
from fastapi import APIRouter, Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.core.auth import SECRET_KEY, HMACAuth


@pytest.fixture
def hmac_app() -> FastAPI:
    """
    Create a FastAPI application instance for testing HMAC authentication.

    Returns:
        FastAPI: FastAPI app with test router configured with HMAC auth.

    """
    app = FastAPI(title="Test HMAC Auth")
    auth = HMACAuth()

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
    signature = hmac.new(SECRET_KEY, b"{}", hashlib.sha256).hexdigest()

    response = await client.post(
        "test/hmac/", headers={"Authorization": f"Signature {signature}"}, json={}
    )

    assert response.status_code == status.HTTP_200_OK


async def test_hmac_authentication_incorrect_signature(client: AsyncClient):
    """Test authentication is successful when signature is correct."""
    response = await client.post(
        "test/hmac/", headers={"Authorization": "Signature nonsense-signature"}, json={}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
