"""
Class for managing robots used to request enhancements from.

Intended to be replaced with a Model and a persistence class at a later date.
"""

from uuid import UUID

from pydantic import BaseModel, HttpUrl

from app.domain.references.models.models import EnhancementType, ExternalIdentifierType


class RobotConfig(BaseModel):
    """
    Primitive configuration for a robot.

    To be replaced with a full persistence implementation at a later date.
    """

    robot_id: UUID
    robot_url: HttpUrl
    # Future implementation should configure whether each dependency is required
    # or provided on a best-efforts basis.
    dependent_enhancements: list[EnhancementType]
    dependent_identifiers: list[ExternalIdentifierType]
    # Secret to be stored in the azure keyvault
    communication_secret_name: str
