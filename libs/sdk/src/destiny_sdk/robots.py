"""Schemas that define inputs/outputs for robots."""

from typing import Annotated

from pydantic import UUID4, BaseModel, Field

from destiny_sdk.enhancements import EnhancementIn
from destiny_sdk.references import Reference


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
    error: RobotError | None = Field(
        default=None,
        description="Error the robot encountered while creating enhancement.",
    )
    enhancement: EnhancementIn | None = Field(
        default=None, description="An enhancement to create"
    )


class RobotRequest(BaseModel):
    """An enhancement request from the repo to a robot."""

    id: UUID4
    reference: Reference  # Reference with selected enhancements
    extra_fields: (
        dict | None
    )  # We need something to pass through the signed url for uploads


class _EnhancementRequestBase(BaseModel):
    """
    Base enhancement request class.

    An enhancement request is a request to create an enhancement on a reference.
    It contains the reference and the robot to be used to create the enhancement.
    """

    reference_id: UUID4 = Field(description="The ID of the reference to be enhanced.")
    robot_id: UUID4 = Field(
        description="The robot to be used to create the enhancement."
    )

    enhancement_parameters: dict | None = Field(
        default=None, description="Information needed to create the enhancement. TBC."
    )


class EnhancementRequestIn(_EnhancementRequestBase):
    """The model for requesting an enhancement on specific reference."""


class EnhancementRequest(_EnhancementRequestBase):
    """Core enhancement request class."""

    id: UUID4
    request_status: str = Field(
        description="The status of the request to create an enhancement",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process",
    )
