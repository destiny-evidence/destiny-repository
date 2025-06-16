"""Tests for the robot management router."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IntegrityError, NotFoundError
from app.domain.robots import routes as robots
from app.domain.robots.sql import Robot as SQLRobot
from app.main import integrity_exception_handler, not_found_exception_handler


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI(
        exception_handlers={
            IntegrityError: integrity_exception_handler,
            NotFoundError: not_found_exception_handler,
        }
    )

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


@pytest.fixture
def robot_t_1000():
    """Return dictionary of basic robot fields."""
    return {
        "base_url": "http://www.mimetic-alloy.com",
        "name": "T-1000",
        "owner": "Skynet",
        "description": "Liquid metal android assassin.",
    }


async def test_register_robot_happy_path(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test registering a robot."""
    response = await client.post("/robot/", json=robot_t_1000)

    assert response.status_code == status.HTTP_201_CREATED
    data = await session.get(SQLRobot, response.json()["id"])
    assert data is not None


async def test_add_robot_fails_when_name_is_the_same(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test that registering a robot with the same name causes a 409 response."""
    existing_robot = SQLRobot(client_secret="secret-secret", **robot_t_1000)
    session.add(existing_robot)
    await session.commit()

    response = await client.post("/robot/", json=robot_t_1000)
    assert response.status_code == status.HTTP_409_CONFLICT


async def test_update_robot_happy_path(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test that updating an existing robot succeeds."""
    existing_robot = SQLRobot(client_secret="secret-secret", **robot_t_1000)
    session.add(existing_robot)
    await session.commit()

    robot_update = robot_t_1000.copy()
    new_description = "Melted and decomissioned."
    robot_update["description"] = new_description
    robot_update["id"] = str(existing_robot.id)

    response = await client.put("/robot/", json=robot_update)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(existing_robot.id)

    await session.refresh(existing_robot)
    assert existing_robot.description == new_description


async def test_update_robot_fails_if_name_is_the_same_as_other_robots(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test that trying to update the name of a robot to something non-unique fails."""
    robot_t_800 = {
        "base_url": "http://www.robotic-endoskeleton.com",
        "name": "T-800",
        "owner": "Skynet",
        "description": "Cyberdyne Systems Model 101",
    }

    robot_to_update = SQLRobot(client_secret="even-more-secret", **robot_t_800)

    session.add(SQLRobot(client_secret="secret-secret", **robot_t_1000))
    session.add(robot_to_update)
    await session.commit()

    robot_update = robot_t_800.copy()
    robot_update["name"] = robot_t_1000["name"]
    robot_update["id"] = str(robot_to_update.id)

    response = await client.put("/robot/", json=robot_update)
    assert response.status_code == status.HTTP_409_CONFLICT


async def test_update_robot_fails_if_try_to_specify_client_secret(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test that trying to update the client secret fails."""
    robot = SQLRobot(client_secret="even-more-secret", **robot_t_1000)

    session.add(robot)
    await session.commit()

    robot_update = robot_t_1000.copy()
    robot_update["id"] = str(robot.id)
    robot_update["client_secret"] = "this isn't allowed!"

    response = await client.put("/robot/", json=robot_update)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_get_robot_happy_path(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test we can get an existing robot."""
    robot = SQLRobot(client_secret="even-more-secret", **robot_t_1000)

    session.add(robot)
    await session.commit()

    response = await client.get(f"/robot/{robot.id}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "T-1000"


async def test_get_robot_robot_does_not_exist(
    session: AsyncSession,  # noqa: ARG001
    client: AsyncClient,
) -> None:
    """Test returns 404 if the requested robot does not exist."""
    response = await client.get(f"/robot/{uuid.uuid4()}/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_cycle_robot_secret_happy_path(
    session: AsyncSession, client: AsyncClient, robot_t_1000: dict[str, str]
) -> None:
    """Test we can cycle the client secret for a robot."""
    initial_secret = "even-more-secret"
    robot = SQLRobot(client_secret=initial_secret, **robot_t_1000)

    session.add(robot)
    await session.commit()

    response = await client.post(f"/robot/{robot.id}/secret/")
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["client_secret"] != initial_secret

    await session.refresh(robot)
    assert response.json()["client_secret"] == robot.client_secret


async def test_cycle_secret_robot_does_not_exist(
    session: AsyncSession,  # noqa: ARG001
    client: AsyncClient,
) -> None:
    """Test returns 404 if robot does not exist."""
    response = await client.post(f"/robot/{uuid.uuid4()}/secret/")
    assert response.status_code == status.HTTP_404_NOT_FOUND
