"""Domain model for robots."""

from typing import Any, Self

import destiny_sdk
from pydantic import UUID4, ConfigDict, Field, HttpUrl, Json, SecretStr, ValidationError

from app.core.exceptions import SDKToDomainError
from app.domain.base import DomainBaseModel, SQLAttributeMixin


class Robot(DomainBaseModel, SQLAttributeMixin):
    """Core Robot model."""

    model_config = ConfigDict(extra="forbid")  # Forbid extra fields on robot model

    base_url: HttpUrl = Field(description="The base url where the robot is located.")

    description: str = Field(description="Description of the robot.")

    name: str = Field(description="The name of the robot.")

    owner: str = Field(description="Owner of the robot.")

    client_secret: SecretStr | None = Field(
        default=None,
        description="The secret key used for communicating with this robot.",
    )

    @classmethod
    async def from_sdk(
        cls, data: destiny_sdk.robots.RobotIn | destiny_sdk.robots.Robot
    ) -> Self:
        """Create a Robot from the SDK input model."""
        try:
            return cls.model_validate(data.model_dump())
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    async def to_sdk(self) -> destiny_sdk.robots.Robot:
        """Convert the robot to a Robot SDK model."""
        try:
            model = self.model_dump()
            model.pop("client_secret", None)
            return destiny_sdk.robots.Robot.model_validate(model)
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    async def to_sdk_provisioned(self) -> destiny_sdk.robots.ProvisionedRobot:
        """Convert the robot to a ProvisionedRobot SDK model."""
        try:
            model = self.model_dump()
            if self.client_secret:
                model["client_secret"] = self.client_secret.get_secret_value()
            return destiny_sdk.robots.ProvisionedRobot.model_validate(model)
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    async def get_client_secret(self) -> str:
        """Return the client secret for the robot."""
        if not self.client_secret:
            msg = f"Robot {self.id} has no client secret."
            raise RuntimeError(msg)
        return self.client_secret.get_secret_value()


class RobotAutomation(DomainBaseModel, SQLAttributeMixin):
    """
    Automation model for a robot.

    This is used as a source of truth for an Elasticsearch index that percolates
    references or enhancements against the queries. If a query matches, a request
    is sent to the specified robot to perform the enhancement.
    """

    robot_id: UUID4 = Field(
        description="The ID of the robot that will be used to enhance the reference."
    )
    query: Json[dict[str, Any]] = Field(
        description="The query that will be used to match references against."
    )

    @classmethod
    async def from_sdk(cls, data: destiny_sdk.robots.RobotAutomation) -> Self:
        """Create a RobotAutomation from the SDK input model."""
        return cls.model_validate(data.model_dump())

    async def to_sdk(self) -> destiny_sdk.robots.RobotAutomation:
        """Convert the RobotAutomation to a RobotAutomation SDK model."""
        try:
            return destiny_sdk.robots.RobotAutomation.model_validate(self.model_dump())
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
