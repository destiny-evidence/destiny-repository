"""Anti-corruption service for robots domain."""

import uuid

import destiny_sdk
from pydantic import ValidationError

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.robots.models.models import Robot
from app.domain.service import GenericAntiCorruptionService


class RobotAntiCorruptionService(GenericAntiCorruptionService):
    """Anti-corruption service for translating between Robot domain and SDK models."""

    def robot_from_sdk(
        self, robot_in: destiny_sdk.robots.RobotIn, robot_id: uuid.UUID | None = None
    ) -> Robot:
        """Create a Robot from the SDK input model."""
        try:
            robot = Robot.model_validate(robot_in.model_dump())
            if robot_id:
                robot.id = robot_id
            robot.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return robot

    def robot_to_sdk(self, robot: Robot) -> destiny_sdk.robots.Robot:
        """Convert the robot to a Robot SDK model."""
        try:
            model = robot.model_dump()
            model.pop("client_secret", None)
            return destiny_sdk.robots.Robot.model_validate(model)
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def robot_to_sdk_provisioned(
        self, robot: Robot
    ) -> destiny_sdk.robots.ProvisionedRobot:
        """Convert the robot to a ProvisionedRobot SDK model."""
        try:
            model = robot.model_dump()
            if robot.client_secret:
                model["client_secret"] = robot.client_secret.get_secret_value()
            return destiny_sdk.robots.ProvisionedRobot.model_validate(model)
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception
