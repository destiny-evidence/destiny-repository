"""
Test Known Robot Hybrid Auth.

Successful authentication is via HMAC on a registered robot,
or a successful JWT authentication.
"""

import uuid
from collections.abc import AsyncGenerator, Callable

import destiny_sdk
import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import AuthRole, AuthScope
from app.api.auth import settings as auth_settings
from app.core.config import Environment
from app.domain.references.models.models import EnhancementRequestStatus
from app.domain.references.models.sql import (
    EnhancementRequest as SQLEnhancementRequest,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.routes import enhancement_request_router
from app.domain.robots.models.sql import Robot as SQLRobot


@pytest.fixture
def hmac_app() -> FastAPI:
    """
    Create a FastAPI application instance for testing HMAC authentication.

    Returns:
        FastAPI: FastAPI app with test router configured with HMAC auth.

    """
    app = FastAPI(title="Test HMAC Auth")
    app.include_router(enhancement_request_router, prefix="/v1")
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


@pytest.fixture
async def registered_robot(session: AsyncSession) -> SQLRobot:
    """Create a registered robot for testing."""
    robot = SQLRobot(
        base_url="https://www.balderdash.org",
        client_secret="secret-secret",
        description="it's a robot",
        name="robot",
        owner="owner",
    )
    session.add(robot)
    await session.commit()
    return robot


@pytest.fixture
async def reference(session: AsyncSession) -> SQLReference:
    """Create a reference for testing."""
    ref = SQLReference(visibility=destiny_sdk.visibility.Visibility.PUBLIC)
    session.add(ref)
    await session.commit()
    return ref


@pytest.fixture
async def enhancement_request(
    session: AsyncSession, registered_robot: SQLRobot, reference: SQLReference
) -> SQLEnhancementRequest:
    """Create an enhancement request for testing."""
    request = SQLEnhancementRequest(
        reference_ids=[reference.id],
        robot_id=registered_robot.id,
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(request)
    await session.commit()
    return request


@pytest.fixture
def auth_settings_production():
    """Set auth settings to production and reset after test."""
    auth_settings.env = Environment.PRODUCTION
    yield
    auth_settings.__init__()  # type: ignore[call-args, misc]


@pytest.fixture
def configured_jwt_auth(fake_application_id: str):
    """Configure JWT auth settings for testing."""
    auth_settings.env = Environment.PRODUCTION
    auth_settings.azure_application_id = fake_application_id
    auth_settings.azure_tenant_id = "test_tenant_id"
    yield
    auth_settings.__init__()  # type: ignore[call-args, misc]


async def test_hmac_multi_client_authentication_happy_path(
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
    auth_settings_production: None,  # noqa: ARG001
    registered_robot: SQLRobot,
    enhancement_request: SQLEnhancementRequest,
) -> None:
    """Test authentication is successful when signature is correct."""
    auth = destiny_sdk.client.HMACSigningAuth(
        client_id=registered_robot.id, secret_key=registered_robot.client_secret
    )

    response = await client.get(
        f"/v1/enhancement-requests/{enhancement_request.id}/",
        auth=auth,
    )

    assert response.status_code == status.HTTP_200_OK


async def test_hmac_multi_client_authentication_robot_does_not_exist(
    client: AsyncClient,
    session: AsyncSession,  # noqa: ARG001
    auth_settings_production: None,  # noqa: ARG001,
    enhancement_request: SQLEnhancementRequest,
) -> None:
    """Test authentication fails when robot does not exist."""
    auth = destiny_sdk.client.HMACSigningAuth(
        client_id=uuid.uuid4(), secret_key="nonsense"
    )

    response = await client.get(
        f"/v1/enhancement-requests/{enhancement_request.id}/",
        auth=auth,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_hmac_multi_client_authentication_robot_secret_mismatch(
    client: AsyncClient,
    auth_settings_production: None,  # noqa: ARG001
    registered_robot: SQLRobot,
    enhancement_request: SQLEnhancementRequest,
) -> None:
    """Test authentication fails when signature is correct but secret is wrong."""
    auth = destiny_sdk.client.HMACSigningAuth(
        client_id=registered_robot.id, secret_key="wrong-secret"
    )

    response = await client.get(
        f"/v1/enhancement-requests/{enhancement_request.id}/",
        auth=auth,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_jwt_authentication_happy_path(  # noqa: PLR0913
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
    stubbed_jwks_response: None,  # noqa: ARG001
    generate_fake_token: Callable[
        [dict | None, AuthScope | None, AuthRole | None], str
    ],
    configured_jwt_auth: None,  # noqa: ARG001
    enhancement_request: SQLEnhancementRequest,
) -> None:
    """Test authentication is successful when JWT token is valid."""
    # Generate JWT token with appropriate scope
    token = generate_fake_token(
        {"sub": "test_user"}, None, AuthRole.ENHANCEMENT_REQUEST_WRITER
    )

    response = await client.get(
        f"/v1/enhancement-requests/{enhancement_request.id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_200_OK


async def test_jwt_authentication_failed_jwks_key_lookup(
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
    generate_fake_token: Callable[[dict | None, str | None], str],
    configured_jwt_auth: None,  # noqa: ARG001
    enhancement_request: SQLEnhancementRequest,
) -> None:
    """Test authentication fails when JWKS key lookup fails."""
    # Generate JWT token with appropriate scope
    token = generate_fake_token({"sub": "test_user"}, "enhancement_request.writer")

    response = await client.get(
        f"/v1/enhancement-requests/{enhancement_request.id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    # This should fail because no JWKS keys are stubbed
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
