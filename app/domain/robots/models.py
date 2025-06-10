"""Domain model for robots."""

import secrets
from typing import Self

import destiny_sdk
from pydantic import Field, HttpUrl, SecretStr, ValidationError

from app.core.exceptions import SDKToDomainError
from app.domain.base import DomainBaseModel, SQLAttributeMixin

ENOUGH_BYTES_FOR_SAFETY = 32


class Robot(DomainBaseModel, SQLAttributeMixin):
    """Core Robot model."""

    base_url: HttpUrl = Field(description="The base url where the robot is located.")

    description: str = Field(description="Description of the robot.")

    name: str = Field(description="The name of the robot.")

    owner: str = Field(description="Owner of the robot.")

    client_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY)),
        description="The secret key used for communicating with this robot.",
    )

    @classmethod
    async def from_sdk(cls, data: destiny_sdk.robots.RobotIn) -> Self:
        """Create a Robot from the SDK input model."""
        try:
            return cls.model_validate(data.model_dump())
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    async def to_sdk(self) -> destiny_sdk.robots.ProvisionedRobot:
        """Convert the robot to an sdk model."""
        try:
            model = self.model_dump()
            model["client_secret"] = self.client_secret.get_secret_value()
            return destiny_sdk.robots.ProvisionedRobot.model_validate(model)
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
