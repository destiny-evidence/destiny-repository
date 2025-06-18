"""Tests for HMAC Authentication."""

import time
import uuid
from collections.abc import AsyncGenerator

import destiny_sdk
import pytest
from destiny_sdk.client import create_signature
from fastapi import APIRouter, Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient

TEST_SECRET_KEY = "dlfskdfhgk8ei346oiehslkdfrerikfglser934utofs"
TEST_CLIENT_ID = uuid.uuid4()
REQUEST_BODY = b'{"message": "info"}'


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
    auth = destiny_sdk.client.HMACSigningAuth(
        secret_key=TEST_SECRET_KEY, client_id=TEST_CLIENT_ID
    )

    response = await client.post("test/hmac/", content=REQUEST_BODY, auth=auth)

    assert response.status_code == status.HTTP_200_OK


async def test_hmac_authentication_no_signature(client: AsyncClient):
    """Test authentication fails if the signature is not included."""
    response = await client.post("test/hmac/", content=REQUEST_BODY)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Authorization header missing" in response.json()["detail"]


async def test_hmac_authentication_wrong_auth_type(client: AsyncClient):
    """Test authentication fails if the signature is not included."""
    response = await client.post(
        "test/hmac/",
        content=REQUEST_BODY,
        headers={"Authorization": "Bearer nonsense-token"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "type not supported" in response.json()["detail"]


async def test_hmac_authentication_no_client_id(client: AsyncClient):
    """Test authentication fails when no client id is provided"""
    signature = create_signature(
        secret_key=TEST_SECRET_KEY,
        request_body=REQUEST_BODY,
        client_id=TEST_CLIENT_ID,
        timestamp=time.time(),
    )

    response = await client.post(
        "test/hmac/",
        headers={"Authorization": f"Signature {signature}"},
        content=REQUEST_BODY,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "X-Client-Id header missing" in response.json()["detail"]


async def test_hmac_authentication_invalid_client_id_format(client: AsyncClient):
    """Test authentication fails when no client id is provided"""
    signature = create_signature(
        secret_key=TEST_SECRET_KEY,
        request_body=REQUEST_BODY,
        client_id=TEST_CLIENT_ID,
        timestamp=time.time(),
    )

    response = await client.post(
        "test/hmac/",
        headers={
            "Authorization": f"Signature {signature}",
            "X-Client-Id": "not-a-uuid",
        },
        content=REQUEST_BODY,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid format for client id" in response.json()["detail"]


async def test_hmac_authentication_no_timestamp(client: AsyncClient):
    """Test authentication fails when no client id is provided"""
    signature = create_signature(
        secret_key=TEST_SECRET_KEY,
        request_body=REQUEST_BODY,
        client_id=TEST_CLIENT_ID,
        timestamp=time.time(),
    )

    response = await client.post(
        "test/hmac/",
        headers={
            "Authorization": f"Signature {signature}",
            "X-Client-Id": f"{TEST_CLIENT_ID}",
        },
        content=REQUEST_BODY,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "X-Request-Timestamp header missing" in response.json()["detail"]


async def test_hmac_authentication_request_too_old(client: AsyncClient):
    """Test authentication fails when no client id is provided"""
    six_minutes = 60 * 6
    signature = create_signature(
        secret_key=TEST_SECRET_KEY,
        request_body=REQUEST_BODY,
        client_id=TEST_CLIENT_ID,
        timestamp=time.time(),
    )

    response = await client.post(
        "test/hmac/",
        headers={
            "Authorization": f"Signature {signature}",
            "X-Client-Id": f"{TEST_CLIENT_ID}",
            "X-Request-Timestamp": f"{time.time() - six_minutes}",
        },
        content=REQUEST_BODY,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Request timestamp has expired." in response.json()["detail"]


async def test_hmac_authentication_incorrect_signature(client: AsyncClient):
    """Test authentication fails when the signature does not match."""
    response = await client.post(
        "test/hmac/",
        headers={
            "Authorization": "Signature nonsense-signature",
            "X-Client-Id": f"{TEST_CLIENT_ID}",
            "X-Request-Timestamp": f"{time.time()}",
        },
        content=REQUEST_BODY,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Signature" in response.json()["detail"]
