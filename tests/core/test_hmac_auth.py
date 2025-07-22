"""Test Known Robot HMAC Auth."""

import uuid
from collections.abc import AsyncGenerator

import destiny_sdk
import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import settings as auth_settings
from app.core.config import Environment
from app.domain.references.models.models import EnhancementRequestStatus
from app.domain.references.models.sql import EnhancementRequest as SQLEnhancementRequest
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.routes import robot_router
from app.domain.robots.models.sql import Robot as SQLRobot


@pytest.fixture
def hmac_app() -> FastAPI:
    """
    Create a FastAPI application instance for testing HMAC authentication.

    Returns:
        FastAPI: FastAPI app with test router configured with HMAC auth.

    """
    app = FastAPI(title="Test HMAC Auth")
    app.include_router(robot_router)
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


async def test_hmac_multi_client_authentication_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test authentication is successful when signature is correct."""
    auth_settings.env = Environment.PRODUCTION

    registered_robot = SQLRobot(
        base_url="https://www.balderdash.org",
        client_secret="secret-secret",
        description="it's a robot",
        name="robot",
        owner="owner",
    )

    reference = SQLReference(visibility=destiny_sdk.visibility.Visibility.PUBLIC)

    session.add(registered_robot)
    session.add(reference)

    await session.commit()

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=registered_robot.id,
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )

    session.add(enhancement_request)
    await session.commit()

    robot_result = destiny_sdk.robots.RobotResult(
        request_id=enhancement_request.id,
        error=destiny_sdk.robots.RobotError(
            message="Robot couldn't create enhancement"
        ),
    )

    auth = destiny_sdk.client.HMACSigningAuth(
        client_id=registered_robot.id, secret_key=registered_robot.client_secret
    )

    response = await client.post(
        "robot/enhancement/single/",
        json=robot_result.model_dump(mode="json"),
        auth=auth,
    )

    assert response.status_code == status.HTTP_200_OK
    # Reset the overridden setting
    auth_settings.__init__()  # type: ignore[call-args, misc]


async def test_hmac_multi_client_authentication_robot_does_not_exist(
    client: AsyncClient,
) -> None:
    """Test authentication is successful when signature is correct."""
    auth_settings.env = Environment.PRODUCTION

    robot_result = destiny_sdk.robots.RobotResult(
        request_id=uuid.uuid4(),
        error=destiny_sdk.robots.RobotError(
            message="Robot couldn't create enhancement"
        ),
    )

    auth = destiny_sdk.client.HMACSigningAuth(
        client_id=uuid.uuid4(), secret_key="nonsense"
    )

    response = await client.post(
        "robot/enhancement/single/",
        json=robot_result.model_dump(mode="json"),
        auth=auth,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Reset the overridden setting
    auth_settings.__init__()  # type: ignore[call-args, misc]
