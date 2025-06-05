"""Test Known Robot HMAC Auth."""

import uuid
from collections.abc import AsyncGenerator

import destiny_sdk
import pytest
from fastapi import APIRouter, Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import UUID4

from app.core.auth import HMACMultiClientAuth
from app.domain.robots.models import Robot

robot = Robot(
    id=uuid.uuid4(),
    base_url="https://www.balderdash.org",
    client_secret="secret-secret",
    description="it's a robot",
    name="robot",
    owner="owner",
)


@pytest.fixture
def hmac_app() -> FastAPI:
    """
    Create a FastAPI application instance for testing HMAC authentication.

    Returns:
        FastAPI: FastAPI app with test router configured with HMAC auth.

    """
    app = FastAPI(title="Test HMAC Auth")

    async def __get_secret(client_id: UUID4) -> str:  # noqa: ARG001
        """Return the test robot secret."""
        return robot.client_secret.get_secret_value()

    auth = HMACMultiClientAuth(get_client_secret=__get_secret)

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


async def test_hmac_multi_client_authentication_happy_path(client: AsyncClient):
    """Test authentication is successful when signature is correct."""
    request_body = '{"message": "info"}'
    auth = destiny_sdk.client.HMACSigningAuth(
        secret_key=robot.client_secret.get_secret_value(), client_id=robot.id
    )

    response = await client.post("test/hmac/", content=request_body, auth=auth)

    assert response.status_code == status.HTTP_200_OK
