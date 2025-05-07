"""Schemas that define inputs/outputs for robots."""

from typing import Annotated, Self

from pydantic import UUID4, BaseModel, Field, model_validator

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
    error: RobotError | None = Field(
        default=None,
        description="Error the robot encountered while creating enhancement.",
    )
    enhancement: EnhancementCreate | None = Field(
        default=None, description="An enhancement to create"
    )

    @model_validator(mode="after")
    def validate_error_or_enhancement_set(self) -> Self:
        """Validate that a robot result has either an error or an enhancement set."""
        if not self.error and not self.enhancement:
            msg = """
            either 'error' or 'enhancements' must be provided
            """
            raise ValueError(msg)
        return self


class RobotRequest(BaseModel):
    """An enhancement request from the repo to a robot."""

    id: UUID4
    reference: Reference  # Reference with selected enhancements
    extra_fields: dict  # We need something to pass through the signed url for uploads
