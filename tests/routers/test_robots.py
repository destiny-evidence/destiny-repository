"""Tests for the robot management router."""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateError
from app.domain.robots import routes as robots
from app.domain.robots.sql import Robot as SQLRobot
from app.main import duplicate_exception_handler


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI(exception_handlers={DuplicateError: duplicate_exception_handler})

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


async def test_add_robot_fails_when_name_is_the_same(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test that registering a robot with the same name causes a 409 response."""
    robot_in = {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }

    existing_robot = SQLRobot(client_secret="secret-secret", **robot_in)
    session.add(existing_robot)
    await session.commit()

    response = await client.post("/robot/", json=robot_in)
    assert response.status_code == status.HTTP_409_CONFLICT


async def test_update_robot_happy_path(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test that updating an existing robot succeeds."""
    robot = {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }

    existing_robot = SQLRobot(client_secret="secret-secret", **robot)
    session.add(existing_robot)
    await session.commit()

    robot_update = robot.copy()
    new_description = "Melted and decomissioned."
    robot_update["description"] = new_description
    robot_update["id"] = str(existing_robot.id)

    response = await client.put("/robot/", json=robot_update)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(existing_robot.id)

    await session.refresh(existing_robot)
    assert existing_robot.description == new_description


async def test_update_robot_fails_if_name_is_the_same_as_other_robots(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test that trying to update the name of a robot to something non-unique fails."""
    robot_1 = {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }

    robot_2 = {
        "base_url": "http://www.robotic-endoskeleton.com",
        "name": "T-800",
        "owner": "Skynet",
        "description": "Cyberdyne Systems Model 101",
    }

    robot_to_update = SQLRobot(client_secret="even-more-secret", **robot_2)

    session.add(SQLRobot(client_secret="secret-secret", **robot_1))
    session.add(robot_to_update)
    await session.commit()

    robot_update = robot_2.copy()
    robot_update["name"] = robot_1["name"]
    robot_update["id"] = str(robot_to_update.id)

    response = await client.put("/robot/", json=robot_update)
    assert response.status_code == status.HTTP_409_CONFLICT


async def test_update_robot_fails_if_try_to_specify_client_secret(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test that trying to update the name of a robot to something non-unique fails."""
    existing_robot = {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }

    robot = SQLRobot(client_secret="even-more-secret", **existing_robot)

    session.add(robot)
    await session.commit()

    robot_update = existing_robot.copy()
    robot_update["id"] = str(robot.id)
    robot_update["client_secret"] = "this isn't allowed!"

    response = await client.put("/robot/", json=robot_update)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_get_robot_happy_path(session: AsyncSession, client: AsyncClient) -> None:
    """Test we can get an existing robot."""
    robot_in = {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }

    robot = SQLRobot(client_secret="even-more-secret", **robot_in)

    session.add(robot)
    await session.commit()

    response = await client.get(f"/robot/{robot.id}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "T-1000"
