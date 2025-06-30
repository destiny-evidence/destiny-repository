"""Schemas that define inputs/outputs for robots."""

from enum import StrEnum, auto
from typing import Annotated, Any, Self

from pydantic import UUID4, BaseModel, ConfigDict, Field, HttpUrl, model_validator

from destiny_sdk.core import _JsonlFileInputMixIn
from destiny_sdk.enhancements import Enhancement
from destiny_sdk.references import Reference


class RobotError(BaseModel):
    """A record of something going wrong with the robot."""

    message: Annotated[
        str,
        Field(
            description=(
                "Message which describes the error encountered during processing"
            )
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
    error: RobotError | None = Field(
        default=None,
        description="""
Error the robot encountered while creating enhancements. If this field is populated,
we assume the entire batch or request failed, rather than an individual reference.
If there was an error with processing an individual reference, it should be passed in
the result file and this field should be left as None. Vice-versa, if this field is
None, the repository will assume that the result file is ready for processing.
""",
    )


class BatchRobotResultValidationEntry(_JsonlFileInputMixIn, BaseModel):
    """A single entry in the validation result file for a batch enhancement request."""

    reference_id: UUID4 | None = Field(
        default=None,
        description=(
            "The ID of the reference which was enhanced. "
            "If this is empty, the BatchEnhancementResultEntry could not be parsed."
        ),
    )
    error: str | None = Field(
        default=None,
        description=(
            "Error encountered during the enhancement process for this reference. "
            "If this is empty, the enhancement was successfully created."
        ),
    )


class RobotRequest(BaseModel):
    """An enhancement request from the repo to a robot."""

    id: UUID4
    reference: Reference = Field(
        description=(
            "Reference to be enhanced, includes identifiers and existing enhancments."
        )
    )
    extra_fields: dict | None = Field(
        default=None,
        description="Extra fields to pass to the robot. TBC.",
    )


#: The result for a single reference when processed by a batch enhancement request.
#: This is a single entry in the result file.
BatchEnhancementResultEntry = Annotated[
    Enhancement | LinkedRobotError,
    Field(),
]


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
If the URL expires, a new one can be generated using
``GET /references/enhancement/batch/<batch_request_id>``.
"""
    )
    result_storage_url: HttpUrl = Field(
        description="""
The URL at which the set of enhancements are to be stored. The file is to be a jsonl
with each line formatted according to
:class:`BatchEnhancementResultEntry <libs.sdk.src.destiny_sdk.robots.BatchEnhancementResultEntry>`.
If the URL expires, a new one can be generated using
``GET /references/enhancement/batch/<batch_request_id>``.
"""  # noqa: E501
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

    RECEIVED = auto()
    ACCEPTED = auto()
    REJECTED = auto()
    FAILED = auto()
    COMPLETED = auto()


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
    source: str | None = Field(
        default=None,
        description="The source of the batch enhancement request.",
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
    - `received`: Enhancement request has been received by the repo.
    - `accepted`: Enhancement request has been accepted by the robot.
    - `rejected`: Enhancement request has been rejected by the robot.
    - `partial_failed`: Some enhancements failed to create.
    - `failed`: All enhancements failed to create.
    - `importing`: Enhancements have been received by the repo and are being imported.
    - `indexing`: Enhancements have been imported and are being indexed.
    - `indexing_failed`: Enhancements have been imported but indexing failed.
    - `completed`: All enhancements have been created.
    """

    RECEIVED = auto()
    ACCEPTED = auto()
    REJECTED = auto()
    PARTIAL_FAILED = auto()
    FAILED = auto()
    IMPORTING = auto()
    INDEXING = auto()
    INDEXING_FAILED = auto()
    COMPLETED = auto()


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
    source: str | None = Field(
        default=None,
        description="The source of the batch enhancement request.",
    )


class BatchEnhancementRequestIn(_BatchEnhancementRequestBase):
    """The model for requesting multiple enhancements on specific references."""


class BatchEnhancementRequestRead(_BatchEnhancementRequestBase):
    """Core batch enhancement request class."""

    id: UUID4
    request_status: BatchEnhancementRequestStatus = Field(
        description="The status of the request to create enhancements",
    )
    reference_data_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL at which the set of references are stored. The file is a jsonl with each line
formatted according to
:class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>`.
, one reference per line.
Each reference may have identifiers or enhancements attached, as
required by the robot.
If the URL expires, a new one can be generated using
``GET /references/enhancement/batch/<batch_request_id>``.
        """,
    )
    result_storage_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL at which the set of enhancements are stored. The file is to be a jsonl
with each line formatted according to
:class:`BatchEnhancementResultEntry <libs.sdk.src.destiny_sdk.robots.BatchEnhancementResultEntry>`.
This field is only relevant to robots.
If the URL expires, a new one can be generated using
``GET /references/enhancement/batch/<batch_request_id>``.
        """,  # noqa: E501
    )
    validation_result_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL at which the result of the batch enhancement request is stored.
This file is a txt file, one line per reference, with either an error
or a success message.
If the URL expires, a new one can be generated using
``GET /references/enhancement/batch/<batch_request_id>``.
        """,
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process. This "
        "is only used if the entire batch enhancement request failed, rather than an "
        "individual reference. If there was an error with processing an individual "
        "reference, it is passed in the validation result file.",
    )


class _RobotBase(BaseModel):
    """
    Base Robot class.

    A Robot is a provider of enhancements to destiny repository
    """

    model_config = ConfigDict(extra="forbid")  # Forbid extra fields on robot models

    name: str = Field(description="The name of the robot, must be unique.")
    base_url: HttpUrl = Field(
        description="The base url of the robot. The robot must implement endpoints "
        "base_url/single for the enhancement of single references and "
        "base_url/batch for batch enhancements of references.",
    )
    description: str = Field(
        description="Description of the enhancement the robot provides."
    )
    owner: str = Field(description="The owner/publisher of the robot.")


class RobotIn(_RobotBase):
    """The model for registering a new robot."""


class Robot(_RobotBase):
    """Then model for a registered robot."""

    id: UUID4 = Field(
        description="The id of the robot provided by destiny repository. "
        "Used as the client_id when sending HMAC authenticated requests."
    )


class ProvisionedRobot(Robot):
    """
    The model for a provisioned robot.

    Used only when a robot is initially created,
    or when cycling a robot's client_secret.
    """

    client_secret: str = Field(
        description="The client secret of the robot, used as the secret key "
        "when sending HMAC authenticated requests."
    )


class _RobotAutomationBase(BaseModel):
    """Base Robot Automation class."""

    query: dict[str, Any] = Field(
        description="The percolator query that will be used to match references "
        " or enhancements against."
    )


class RobotAutomationIn(_RobotAutomationBase):
    """
    Automation model for a robot.

    This is used as a source of truth for an Elasticsearch index that percolates
    references or enhancements against the queries. If a query matches, a request
    is sent to the specified robot to perform the enhancement.
    """


class RobotAutomation(_RobotAutomationBase):
    """
    Core Robot Automation class.

    This is used as a source of truth for an Elasticsearch index that percolates
    references or enhancements against the queries. If a query matches, a request
    is sent to the specified robot to perform the enhancement.
    """

    id: UUID4 = Field(
        description="The ID of the robot automation.",
    )
    robot_id: UUID4 = Field(
        description="The ID of the robot that will be used to enhance the reference."
    )
