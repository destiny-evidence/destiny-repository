"""Models used by the `Import` domain."""

import datetime
import uuid
from enum import StrEnum, auto
from typing import Self

import destiny_sdk
from pydantic import Field, HttpUrl, PastDatetime, ValidationError

from app.core.exceptions import SDKToDomainError
from app.domain.base import DomainBaseModel, SQLAttributeMixin


class ImportRecordStatus(StrEnum):
    """
    Describes the status of an import record.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = auto()
    STARTED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class ImportBatchStatus(StrEnum):
    """
    Describes the status of an import batch.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `retrying`: Processing has failed, but is being retried.
    - `failed`: Processing has failed, and may or may not be solved with a retry.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = auto()
    STARTED = auto()
    RETRYING = auto()
    FAILED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class CollisionStrategy(StrEnum):
    """
    The strategy to use when an identifier collision is detected.

    Identifier collisions are detected on ``identifier_type`` and ``identifier``
    (and ``other_identifier_name`` where relevant) already present in the database.

    Enhancement collisions are detected on an entry with matching ``enhancement_type``
    and ``source`` already being present on the collided reference.

    - `discard`: Do nothing with the incoming reference.
    - `fail`: Do nothing with the incoming reference and mark it as failed. This
      allows the importing process to "follow up" on the failure.
    - `merge_aggressive`: Prioritize the incoming reference's identifiers and
      enhancements in the merge.
    - `merge_defensive`: Prioritize the existing reference's identifiers and
      enhancements in the merge.
    - `append`: Performs an aggressive merge of identifiers, and an append of
      enhancements.
    - `overwrite`: Performs an aggressive merge of identifiers, and an overwrite of
      enhancements (deleting existing and recreating what is imported). This should
      be used sparingly and carefully.
    """

    DISCARD = auto()
    FAIL = auto()
    MERGE_AGGRESSIVE = auto()
    MERGE_DEFENSIVE = auto()
    APPEND = auto()
    OVERWRITE = auto()


class ImportResultStatus(StrEnum):
    """
    Describes the status of an import result.

    - `created`: Created, but no processing has started.
    - `started`: The reference is currently being processed.
    - `completed`: The reference has been created.
    - `partially_failed`: The reference was created but one or more enhancements or
      identifiers failed to be added. See the result's `failure_details` field for
      more information.
    - `failed`: The reference failed to be created. See the result's `failure_details`
      field for more information.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = auto()
    STARTED = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    PARTIALLY_FAILED = auto()
    FAILED = auto()


class ImportRecord(DomainBaseModel, SQLAttributeMixin):
    """Core import record model with database and internal attributes included."""

    search_string: str | None = Field(
        default=None,
        description="The search string used to produce this import",
    )
    searched_at: PastDatetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC),
        description="""
The timestamp (including timezone) at which the search which produced
this import was conducted. If no timezone is included, the timestamp
is assumed to be in UTC.
        """,
    )
    processor_name: str = Field(
        description="The name of the processor that is importing the data."
    )
    processor_version: str = Field(
        description="The version of the processor that is importing the data."
    )
    notes: str | None = Field(
        default=None,
        description="""
Any additional notes regarding the import (eg. reason for importing, known
issues).
        """,
    )
    expected_reference_count: int = Field(
        description="""
The number of references expected to be included in this import.
-1 is accepted if the number is unknown.
""",
        ge=-1,
    )
    source_name: str = Field(
        description="The source of the reference being imported (eg. Open Alex)"
    )

    status: ImportRecordStatus = Field(
        default=ImportRecordStatus.CREATED,
        description="The status of the upload.",
    )
    batches: list["ImportBatch"] | None = Field(
        default=None, description="The batches associated with this import."
    )

    @classmethod
    async def from_sdk(cls, data: destiny_sdk.imports.ImportRecordIn) -> Self:
        """Create an ImportRecord from the SDK input model."""
        try:
            c = cls.model_validate(data.model_dump())
            c.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return c

    async def to_sdk(self) -> destiny_sdk.imports.ImportRecordRead:
        """Convert the ImportRecord to the SDK model."""
        try:
            return destiny_sdk.imports.ImportRecordRead.model_validate(
                self.model_dump()
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception


class ImportBatch(DomainBaseModel, SQLAttributeMixin):
    """Core import batch model with database and internal attributes included."""

    collision_strategy: CollisionStrategy = Field(
        default=CollisionStrategy.FAIL,
        description="""
The strategy to use for each reference when an identifier collision occurs.
Default is `fail`, which allows the importing process to "follow up" on the collision.
        """,
    )
    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored.
    """,
    )
    callback_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL to which the processor should send a callback when the batch has been processed.
        """,
    )
    status: ImportBatchStatus = Field(
        default=ImportBatchStatus.CREATED, description="The status of the batch."
    )
    import_record_id: uuid.UUID = Field(
        description="The ID of the parent import record."
    )
    import_record: ImportRecord | None = Field(
        default=None, description="The parent import record."
    )
    import_results: list["ImportResult"] | None = Field(
        default=None, description="The results from processing the batch."
    )

    @classmethod
    async def from_sdk(
        cls, data: destiny_sdk.imports.ImportBatchIn, import_record_id: uuid.UUID
    ) -> Self:
        """Create an ImportBatch from the SDK input model."""
        try:
            c = cls.model_validate(
                data.model_dump() | {"import_record_id": import_record_id}
            )
            c.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return c

    async def to_sdk(self) -> destiny_sdk.imports.ImportBatchRead:
        """Convert the ImportBatch to the SDK model."""
        try:
            return destiny_sdk.imports.ImportBatchRead.model_validate(self.model_dump())
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    async def to_sdk_summary(self) -> destiny_sdk.imports.ImportBatchSummary:
        """Convert the ImportBatch to the SDK summary model."""
        try:
            result_summary: dict[ImportResultStatus, int] = dict.fromkeys(
                ImportResultStatus, 0
            )
            failure_details: list[str] = []
            for result in self.import_results or []:
                result_summary[result.status] += 1
                if (
                    result.status
                    in (
                        ImportResultStatus.FAILED,
                        ImportResultStatus.PARTIALLY_FAILED,
                    )
                    and result.failure_details
                ):
                    failure_details.append(result.failure_details)
            return destiny_sdk.imports.ImportBatchSummary.model_validate(
                self.model_dump()
                | {
                    "import_batch_id": self.id,
                    "import_batch_status": self.status,
                    "results": result_summary,
                    "failure_details": failure_details,
                }
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception


class ImportResult(DomainBaseModel, SQLAttributeMixin):
    """Core import result model with database attributes included."""

    import_batch_id: uuid.UUID = Field(description="The ID of the parent import batch.")
    status: ImportResultStatus = Field(
        default=ImportResultStatus.CREATED, description="The status of the result."
    )
    import_batch: ImportBatch | None = Field(
        default=None, description="The parent import batch."
    )
    reference_id: uuid.UUID | None = Field(
        default=None, description="The ID of the created reference."
    )
    failure_details: str | None = Field(
        default=None,
        description="Details of any failure that occurred during processing.",
    )

    async def to_sdk(self) -> destiny_sdk.imports.ImportResultRead:
        """Convert the ImportResult to the SDK model."""
        try:
            return destiny_sdk.imports.ImportResultRead.model_validate(
                self.model_dump()
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
