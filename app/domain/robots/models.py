"""Domain model for robots."""

from pydantic import Field, HttpUrl, SecretStr

from app.domain.base import DomainBaseModel, SQLAttributeMixin


class Robot(DomainBaseModel, SQLAttributeMixin):
    """Core Robot model."""

    base_url: HttpUrl = Field(description="The base url where the robot is located.")

    client_secret: SecretStr = Field(
        description="The secret key used for communicating with this robot."
    )

    description: str = Field(description="Description of the robot.")

    name: str = Field(description="The name of the robot.")

    owner: str = Field(description="Owner of the robot.")
