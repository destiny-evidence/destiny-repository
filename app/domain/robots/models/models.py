"""Domain model for robots."""

from destiny_sdk.robots import RobotEntitlement
from pydantic import ConfigDict, Field, SecretStr

from app.domain.base import DomainBaseModel, SQLAttributeMixin


class Robot(DomainBaseModel, SQLAttributeMixin):
    """Core Robot model."""

    model_config = ConfigDict(extra="forbid")  # Forbid extra fields on robot model

    description: str = Field(description="Description of the robot.")

    name: str = Field(description="The name of the robot.")

    owner: str = Field(description="Owner of the robot.")

    entitlements: frozenset[RobotEntitlement] = Field(
        default_factory=frozenset,
        description="Entitlements granted to this robot.",
    )

    client_secret: SecretStr | None = Field(
        default=None,
        description="The secret key used for communicating with this robot.",
    )

    def get_client_secret(self) -> str:
        """Return the client secret for the robot."""
        if not self.client_secret:
            msg = f"Robot {self.id} has no client secret."
            raise RuntimeError(msg)
        return self.client_secret.get_secret_value()
