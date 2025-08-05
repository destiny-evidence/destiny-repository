"""Router for handling management of robots."""

import uuid
from typing import Annotated

import destiny_sdk
from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger
from structlog.stdlib import BoundLogger

from app.api.auth import (
    AuthMethod,
    AuthScopes,
    CachingStrategyAuth,
    choose_auth_strategy,
)
from app.core.config import get_settings
from app.domain.robots.service import RobotService
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger: BoundLogger = get_logger(__name__)


def sql_unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on robots in SQL."""
    return AsyncSqlUnitOfWork(session=session)


def robot_anti_corruption_service() -> RobotAntiCorruptionService:
    """Return the robot anti-corruption service."""
    return RobotAntiCorruptionService()


def robot_service(
    anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(sql_unit_of_work)],
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(
        anti_corruption_service=anti_corruption_service, sql_uow=sql_uow
    )


def choose_auth_strategy_robot_writer() -> AuthMethod:
    """Choose robot writer for our authorization strategy."""
    return choose_auth_strategy(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScopes.ROBOT_WRITER,
        bypass_auth=settings.running_locally,
    )


robot_writer_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_robot_writer,
)

router = APIRouter(
    prefix="/robots",
    tags=["robot-management"],
    dependencies=[Depends(robot_writer_auth)],
)


@router.put(path="/{robot_id}/", status_code=status.HTTP_200_OK)
async def update_robot(
    robot_id: Annotated[uuid.UUID, Path(description="The id of the robot.")],
    robot_update: destiny_sdk.robots.RobotIn,
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
) -> destiny_sdk.robots.Robot:
    """Update an existing robot."""
    robot = anti_corruption_service.robot_from_sdk(robot_update, robot_id=robot_id)
    updated_robot = await robot_service.update_robot(robot=robot)
    return anti_corruption_service.robot_to_sdk(updated_robot)


@router.post(path="/", status_code=status.HTTP_201_CREATED)
async def register_robot(
    robot_create: destiny_sdk.robots.RobotIn,
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
) -> destiny_sdk.robots.ProvisionedRobot:
    """Register a new robot."""
    robot = anti_corruption_service.robot_from_sdk(robot_create)
    provisioned_robot = await robot_service.add_robot(robot=robot)
    return anti_corruption_service.robot_to_sdk_provisioned(provisioned_robot)


@router.get(path="/{robot_id}/", status_code=status.HTTP_200_OK)
async def get_robot(
    robot_id: Annotated[uuid.UUID, Path(description="The id of the robot.")],
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
) -> destiny_sdk.robots.Robot:
    """Get an existing Robot."""
    robot = await robot_service.get_robot_standalone(robot_id=robot_id)
    return anti_corruption_service.robot_to_sdk(robot)


@router.get(path="/", status_code=status.HTTP_200_OK)
async def get_all_robots(
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
) -> list[destiny_sdk.robots.Robot]:
    """Get all robots."""
    robots = await robot_service.get_all_robots()
    return [anti_corruption_service.robot_to_sdk(robot) for robot in robots]


@router.post(path="/{robot_id}/secret/", status_code=status.HTTP_201_CREATED)
async def cycle_robot_secret(
    robot_id: Annotated[uuid.UUID, Path(description="The id of the robot.")],
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
) -> destiny_sdk.robots.ProvisionedRobot:
    """Cycle the robot's client_secret."""
    robot_secret_cycled = await robot_service.cycle_robot_secret(robot_id=robot_id)
    return anti_corruption_service.robot_to_sdk_provisioned(robot_secret_cycled)
