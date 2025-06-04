"""Domain model for robots."""

from pydantic import Field, HttpUrl, SecretStr

from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.domain.references.models.models import EnhancementType, ExternalIdentifierType


class Robot(DomainBaseModel, SQLAttributeMixin):
    """Core Robot model."""

    robot_base_url: HttpUrl = Field(
        description="The base url where the robot is located."
    )

    robot_secret: SecretStr = Field(
        description="The secret key used for communicating with this robot."
    )

    # Future implementation should configure whether each dependency is required
    # or provided on a best-efforts basis.
    dependent_enhancements: list[EnhancementType] = Field(
        default_factory=list, description="Enhancements that this robot depends on."
    )

    dependent_identifiers: list[ExternalIdentifierType] = Field(
        default_factory=list, description="Identifiers that this robot depends on."
    )
