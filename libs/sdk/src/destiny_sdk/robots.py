"""Schemas that define inputs/outputs for robots."""

from typing import Annotated

from pydantic import UUID4, BaseModel, Field

from destiny_sdk.core import EnhancementCreate, Reference


class RobotError(BaseModel):
    """A record of something going wrong with the robot."""

    message: Annotated[
        str,
        Field(
            description="""
Message which describes the error encountered during processing
"""
        ),
    ]


class RobotResult(BaseModel):
    """The result of a robot request which is returned to the repo."""

    request_id: UUID4
    error: RobotError
    enhancements: list[EnhancementCreate]


class RobotRequest(BaseModel):
    """An enhancement request from the repo to a robot."""

    id: UUID4
    reference: Reference  # Reference with selected enhancements
    extra_fields: dict  # We need something to pass through the signed url for uploads
