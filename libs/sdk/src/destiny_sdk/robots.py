"""Schemas that define inputs/outputs for robots."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import UUID4, BaseModel, Field, HttpUrl, model_validator

from destiny_sdk.enhancements import Enhancement
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
    enhancement: Enhancement | None = Field(
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


class BatchRobotResult(BaseModel):
    """The result of a batch robot request which is returned to the repo."""

    # N.B. I don't know if a robot should be _required_ to use this
    # interface - if it prefers to send results back one-by-one, that's
    # probably still okay? Allows them to distribute the load without
    # worrying about reaggregation.
    # We'll need to think more about how to handle partial failures, below
    # I just use a union type.
    request_id: UUID4
    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of enhancements are stored. The file is a jsonl
formatted according to `enhancements/LinkedEnhancementFileInput|RobotError`.
"""
    )


class RobotRequest(BaseModel):
    """An enhancement request from the repo to a robot."""

    id: UUID4
    reference: Reference  # Reference with selected enhancements
    extra_fields: (
        dict | None
    )  # We need something to pass through the signed url for uploads


class BatchRobotRequest(BaseModel):
    """A batch enhancement request from the repo to a robot."""

    # My focus here is on removing complexity from the robot - the repo
    # should be able to distill the flexible/generalised request into a
    # set of specific requests for the robot(s) to handle.
    # Asking robots to implement endpoints for both single and batch requests
    # feels overwhelming - maybe references should always be a list and
    # robots should just handle the batch request?
    id: UUID4
    references: list[Reference]
    extra_fields: dict | None


class EnhancementRequestStatus(StrEnum):
    """
    The status of an enhancement request.

    **Allowed values**:
    - `received`: Enhancement request has been received.
    - `accepted`: Enhancement request has been accepted.
    - `rejected`: Enhancement request has been rejected.
    - `failed`: Enhancement failed to create.
    - `completed`: Enhancement has been created.
    """

    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    COMPLETED = "completed"


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


class EnhancementRequestRead(_EnhancementRequestBase):
    """Core enhancement request class."""

    id: UUID4
    request_status: EnhancementRequestStatus = Field(
        description="The status of the request to create an enhancement",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process",
    )


class EnhancementRequestFileInput(BaseModel):
    """Enhancement model used to marshall a file input."""

    reference_id: UUID4 = Field(description="The ID of the reference to be enhanced.")
    robot_id: UUID4 = Field(
        description="The robot to be used to create the enhancement."
    )
    enhancement_parameters: dict | None = Field(
        default=None, description="Information needed to create the enhancement. TBC."
    )

    def to_jsonl(self) -> str:
        """Convert the model to a JSONL string."""
        return self.model_dump_json(exclude_none=True)


class BatchEnhancementRequestStatus(StrEnum):
    """
    The status of an enhancement request.

    **Allowed values**:
    - `received`: Enhancement request has been received.
    - `accepted`: Enhancement request has been accepted.
    - `rejected`: Enhancement request has been rejected.
    - `partial_failed`: Some enhancements failed to create.
    - `failed`: All enhancements failed to create.
    - `completed`: All enhancements have been created.
    """

    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    COMPLETED = "completed"


class _BatchEnhancementRequestBase(BaseModel):
    """
    Base batch enhancement request class.

    A batch enhancement request is a request to create multiple enhancements.
    """

    # My focus here is on making the request flexible
    # We can consider putting optional robot_id, reference_id, enhancement_parameters
    # here that would act as defaults on the file to remove duplication on each line
    # I've omitted them for now to keep the process generalisable (eg see the two
    # examples below - an EnhancementRequest doesn't necessarily map to a single
    # robot)

    # We can also consider allowing a list of EnhancementRequestIn, instead of a
    # storage_url? (I.e. one or the other).
    # Requiring a file for _everything_ feels unwieldy. For instance,
    # a common use case to me might be:
    #  - create a reference
    #  - request x enhancements on that reference
    # Which is an order of magnitude smaller than a use case such as:
    #  - create a robot
    #  - request an enhancement on x references

    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of enhancement requests are stored. The file is a jsonl
formatted according to `robots/EnhancementRequestFileInput`.
"""
    )


class BatchEnhancementRequestIn(_BatchEnhancementRequestBase):
    """The model for requesting multiple enhancements on specific references."""


class BatchEnhancementRequestRead(_BatchEnhancementRequestBase):
    """Core batch enhancement request class."""

    id: UUID4
    status: EnhancementRequestStatus = Field(
        description="The status of the request to create enhancements",
    )
    # Should this be a list of errors? Or even a dict of `reference_id: error`?
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process",
    )
