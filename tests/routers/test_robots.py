"""Tests for the robot management router."""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.robots import routes as robots
from app.domain.robots.sql import Robot as SQLRobot


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI()

    app.include_router(robots.router)

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """
    Create a test client for the FastAPI application.

    Args:
        app (FastAPI): FastAPI application instance.

    Returns:
        TestClient: Test client for the FastAPI application.

    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_register_robot_happy_path(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test registering a reference."""
    robot_in = {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }

    response = await client.post("/robot/", json=robot_in)

    assert response.status_code == status.HTTP_201_CREATED
    data = await session.get(SQLRobot, response.json()["id"])
    assert data is not None
