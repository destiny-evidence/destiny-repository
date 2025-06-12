"""Router for handling management of robots."""

import uuid
from typing import Annotated

import destiny_sdk
from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    CachingStrategyAuth,
    choose_auth_strategy,
)
from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.robots.models import Robot
from app.domain.robots.service import RobotService
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger = get_logger()


def unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on references."""
    return AsyncSqlUnitOfWork(session=session)


def robot_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(sql_uow=sql_uow)


def choose_auth_strategy_robot_writer() -> AuthMethod:
    """Choose robot writer for our authorization strategy."""
    return choose_auth_strategy(
        environment=settings.env,
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScopes.ROBOT_WRITER,
    )


robot_writer_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_robot_writer,
)

router = APIRouter(
    prefix="/robot",
    tags=["robot-management"],
    dependencies=[Depends(robot_writer_auth)],
)


@router.put(path="/", status_code=status.HTTP_200_OK)
async def update_robot(
    robot_update: destiny_sdk.robots.Robot,
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> destiny_sdk.robots.Robot:
    """Update an existing robot."""
    robot = await Robot.from_sdk(robot_update)
    updated_robot = await robot_service.update_robot(robot=robot)
    return await updated_robot.to_sdk()


@router.post(path="/", status_code=status.HTTP_201_CREATED)
async def register_robot(
    robot_create: destiny_sdk.robots.RobotIn,
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> destiny_sdk.robots.ProvisionedRobot:
    """Register a new robot."""
    robot = await Robot.from_sdk(robot_create)
    provisioned_robot = await robot_service.add_robot(robot=robot)
    return await provisioned_robot.to_sdk_provisioned()


@router.get(path="/{robot_id}/", status_code=status.HTTP_200_OK)
async def get_robot(
    robot_id: Annotated[uuid.UUID, Path(description="The id of the robot.")],
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> destiny_sdk.robots.Robot:
    """Get an existing Robot."""
    robot = await robot_service.get_robot_standalone(robot_id=robot_id)
    return await robot.to_sdk()


@router.post(path="/{robot_id}/secret/", status_code=status.HTTP_201_CREATED)
async def cycle_robot_secret(
    robot_id: Annotated[uuid.UUID, Path(description="The id of the robot.")],
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> destiny_sdk.robots.ProvisionedRobot:
    """Cycle the robot's client_secret."""
    robot_secret_cycled = await robot_service.cycle_robot_secret(robot_id=robot_id)
    return await robot_secret_cycled.to_sdk_provisioned()
