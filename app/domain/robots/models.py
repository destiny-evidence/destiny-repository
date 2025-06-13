"""Domain model for robots."""

from typing import Self

import destiny_sdk
from pydantic import ConfigDict, Field, HttpUrl, SecretStr, ValidationError

from app.core.exceptions import SDKToDomainError
from app.domain.base import DomainBaseModel, SQLAttributeMixin


class Robot(DomainBaseModel, SQLAttributeMixin):
    """Core Robot model."""

    model_config = ConfigDict(extra="forbid")  # Forbid extra fields on robot model

    base_url: HttpUrl = Field(description="The base url where the robot is located.")

    description: str = Field(description="Description of the robot.")

    name: str = Field(description="The name of the robot.")

    owner: str = Field(description="Owner of the robot.")

    enhance_incoming_references: bool = Field(
        default=False,
        description="Whether this robot should automatically receive enhancement "
        "requests for new references.",
    )

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
