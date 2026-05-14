"""Service for managing Robots."""

import secrets
from uuid import UUID

from destiny_sdk.robots import RobotEntitlement
from fastapi import status
from pydantic import SecretStr

from app.api.auth import ClientAuthInfo, Entitlement
from app.core.exceptions import AuthError
from app.domain.robots.models.models import Robot
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work

ENOUGH_BYTES_FOR_SAFETY = 32


def _resolve_robot_entitlements(
    submitted: frozenset[RobotEntitlement],
    existing: frozenset[RobotEntitlement],
    caller_entitlements: frozenset[Entitlement],
) -> frozenset[RobotEntitlement]:
    """Return the entitlements to persist, enforcing the writer requirement."""
    # Writers may set entitlements freely, including revoking via an empty set.
    if Entitlement.ROBOT_ENTITLEMENT_WRITER in caller_entitlements:
        return submitted
    # Everyone else may only submit no-op inputs: an empty set (treated as
    # "field not specified") or the existing value (round-trip from GET).
    if not submitted or submitted == existing:
        return existing
    raise AuthError(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Changing robot entitlements requires the "
            "robot.entitlement.writer scope or role."
        ),
    )


class RobotService(GenericService[RobotAntiCorruptionService]):
    """Service for creating and managing robots."""

    def __init__(
        self,
        anti_corruption_service: RobotAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the robots."""
        super().__init__(anti_corruption_service, sql_uow)

    async def get_robot(self, robot_id: UUID) -> Robot:
        """Return a given robot."""
        return await self.sql_uow.robots.get_by_pk(robot_id)

    @sql_unit_of_work
    async def get_all_robots(self) -> list[Robot]:
        """Return all robots."""
        return await self.sql_uow.robots.get_all()

    @sql_unit_of_work
    async def get_robot_standalone(self, robot_id: UUID) -> Robot:
        """Return a given robot."""
        return await self.get_robot(robot_id)

    @sql_unit_of_work
    async def get_robot_auth_info(self, robot_id: UUID) -> ClientAuthInfo:
        """Return the HMAC secret and entitlements for a given robot."""
        robot = await self.get_robot(robot_id)
        return ClientAuthInfo(
            secret=robot.get_client_secret(),
            entitlements=robot.entitlements,
        )

    @sql_unit_of_work
    async def add_robot(
        self,
        robot: Robot,
        caller_entitlements: frozenset[Entitlement],
    ) -> Robot:
        """Register a new robot."""
        robot.entitlements = _resolve_robot_entitlements(
            submitted=robot.entitlements,
            existing=frozenset(),
            caller_entitlements=caller_entitlements,
        )
        robot.client_secret = SecretStr(secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY))
        return await self.sql_uow.robots.add(robot)

    @sql_unit_of_work
    async def update_robot(
        self,
        robot: Robot,
        caller_entitlements: frozenset[Entitlement],
    ) -> Robot:
        """Update an existing robot."""
        existing = await self.sql_uow.robots.get_by_pk(robot.id)
        robot.entitlements = _resolve_robot_entitlements(
            submitted=robot.entitlements,
            existing=existing.entitlements,
            caller_entitlements=caller_entitlements,
        )
        return await self.sql_uow.robots.merge(robot)

    @sql_unit_of_work
    async def cycle_robot_secret(self, robot_id: UUID) -> Robot:
        """Cycle the client secret for a given robot."""
        new_client_secret = secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY)
        return await self.sql_uow.robots.update_by_pk(
            robot_id, client_secret=new_client_secret
        )
