"""Schemas that define inputs/outputs for robots."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import UUID4, BaseModel, Field, HttpUrl, model_validator

from destiny_sdk.core import _JsonlFileInputMixIn
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


class LinkedRobotError(_JsonlFileInputMixIn, RobotError):
    """
    A record of something going wrong when processing an individual reference.

    Used in results for batch requests - in single requests, the reference
    id is derived from the request id.
    """

    reference_id: UUID4 = Field(
        description="The ID of the reference which caused the error."
    )


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
        if (self.error is None) == (self.enhancement is None):
            msg = """
            exactly one of 'error' or 'enhancement' must be provided
            """
            raise ValueError(msg)
        return self


class BatchRobotResult(BaseModel):
    """Used to indicate to the repository that the robot has finished processing."""

    request_id: UUID4
    # Note we don't actually use this field in the repo as we have direct access to the
    # file. It's here to both give a robot a way of indicating the file generation was
    # successful and to prompt it to have uploaded the file to the correct location.
    storage_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL at which the set of enhancements are stored. This should match the corresponding
:attr:`BatchRobotRequest.result_storage_url <libs.sdk.src.destiny_sdk.robots.BatchRobotRequest.result_storage_url>`.
The file is to be a jsonl with each line formatted according to
:class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>` or
:class:`LinkedRobotError <libs.sdk.src.destiny_sdk.robots.LinkedRobotError>`.
""",  # noqa: E501
    )
    error: RobotError | None = Field(
        default=None,
        description="""
Error the robot encountered while creating enhancements. This field should
be used if there was an error with the entire batch or the request, rather than an
individual reference. If there was an error with processing an individual reference, it
should be passed in the result file.
""",
    )

    @model_validator(mode="after")
    def validate_error_or_storage_url_set(self) -> Self:
        """Validate that the model has either an error or a storage url set."""
        if (self.error is None) == (self.storage_url is None):
            msg = """
            exactly one of 'error' or 'storage_url' must be provided
            """
            raise ValueError(msg)
        return self


class RobotRequest(BaseModel):
    """An enhancement request from the repo to a robot."""

    id: UUID4
    reference: Reference  # Reference with selected enhancements
    extra_fields: (
        dict | None
    )  # We need something to pass through the signed url for uploads


class BatchRobotRequest(BaseModel):
    """A batch enhancement request from the repo to a robot."""

    id: UUID4
    reference_storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references are stored. The file is a jsonl
with each line formatted according to
:class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>`, one
reference per line.
Each reference may have identifiers or enhancements attached, as
required by the robot.
If the URL expires, a new one can be generated using the <TBC>.
"""
    )
    result_storage_url: HttpUrl = Field(
        description="""
The URL at which the set of enhancements are to be stored. The file is to be a jsonl
with each line formatted according to
:class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>` or
:class:`LinkedRobotError <libs.sdk.src.destiny_sdk.robots.LinkedRobotError>`.
If the URL expires, a new one can be generated using the <TBC>.
"""
    )
    extra_fields: dict | None = Field(
        default=None,
        description="Extra fields to pass to the robot. TBC.",
    )


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


class BatchEnhancementRequestStatus(StrEnum):
    """
    The status of an enhancement request.

    **Allowed values**:
    - `received`: Enhancement request has been received by the robot.
    - `accepted`: Enhancement request has been accepted by the robot.
    - `rejected`: Enhancement request has been rejected by the robot.
    - `partial_failed`: Some enhancements failed to create.
    - `failed`: All enhancements failed to create.
    - `processed`: Enhancements have been received by the repo and are being validated.
    - `completed`: All enhancements have been created.
    """

    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    PROCESSED = "processed"
    COMPLETED = "completed"


class _BatchEnhancementRequestBase(BaseModel):
    """
    Base batch enhancement request class.

    A batch enhancement request is a request to create multiple enhancements.
    """

    robot_id: UUID4 = Field(
        description="The robot to be used to create the enhancements."
    )
    reference_ids: list[UUID4] = Field(
        description="The IDs of the references to be enhanced."
    )


class BatchEnhancementRequestIn(_BatchEnhancementRequestBase):
    """The model for requesting multiple enhancements on specific references."""


class BatchEnhancementRequestRead(_BatchEnhancementRequestBase):
    """Core batch enhancement request class."""

    id: UUID4
    request_status: EnhancementRequestStatus = Field(
        description="The status of the request to create enhancements",
    )
    reference_data_url: str | None = Field(
        default=None,
        description="""
        The URL at which the set of references are stored. The file is a jsonl
        with each line formatted according to
        :class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>`.
        , one reference per line.
        Each reference may have identifiers or enhancements attached, as
        required by the robot.
        TODO: make type HttpUrl once URL signing implemented.
        """,
    )
    # Should this be a list of errors? Or even a dict of `reference_id: error`?
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process",
    )
