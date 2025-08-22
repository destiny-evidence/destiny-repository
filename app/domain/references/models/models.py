"""Models associated with references."""

import uuid
from enum import StrEnum, auto
from typing import Any, Self

import destiny_sdk

# Explicitly import these models for easy use in the rest of the codebase
from destiny_sdk.enhancements import EnhancementContent, EnhancementType  # noqa: F401
from destiny_sdk.identifiers import ExternalIdentifier, ExternalIdentifierType
from pydantic import (
    UUID4,
    BaseModel,
    Field,
    TypeAdapter,
)

from app.core.config import get_settings
from app.core.exceptions import UnresolvableReferenceDuplicateError
from app.core.telemetry.logger import get_logger
from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.persistence.blob.models import BlobStorageFile

logger = get_logger(__name__)
settings = get_settings()

ExternalIdentifierAdapter: TypeAdapter[ExternalIdentifier] = TypeAdapter(
    ExternalIdentifier,
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


class Visibility(StrEnum):
    """
    The visibility of a data element in the repository.

    This is used to manage whether information should be publicly available or
    restricted (generally due to copyright constraints from publishers).

    TODO: Implement data governance layer to manage this.

    **Allowed values**:

    - `public`: Visible to the general public without authentication.
    - `restricted`: Requires authentication to be visible.
    - `hidden`: Is not visible, but may be passed to data mining processes.
    """

    PUBLIC = auto()
    RESTRICTED = auto()
    HIDDEN = auto()


class Reference(
    DomainBaseModel,
    SQLAttributeMixin,
):
    """Core reference model with database attributes included."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list["LinkedExternalIdentifier"] | None = Field(
        default=None,
        description="A list of `LinkedExternalIdentifiers` for the Reference",
    )
    enhancements: list["Enhancement"] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )
    duplicate_of: uuid.UUID | None = Field(
        default=None,
        description="The ID of the canonical reference that this reference duplicates",
    )
    canonical_reference: "Reference | None" = Field(
        default=None,
        description="The canonical reference that this reference is a duplicate of",
    )
    duplicate_references: list["Reference"] | None = Field(
        default=None,
        description="A list of references that this reference duplicates",
    )

    def merge(
        self,
        identifiers: list["LinkedExternalIdentifier"],
        enhancements: list["Enhancement"],
        duplicate_depth: int = 1,
        *,
        propagate_upwards: bool = True,
    ) -> tuple[list["LinkedExternalIdentifier"], list["Enhancement"]]:
        """
        Merge an incoming reference into this one.

        **Enhancements**
        Appends any enhancements, unless the incoming enhancement is identical to an
        existing enhancement.

        **Identifiers**
        Appends any identifiers, unless the incoming identifier is identical to an
        existing identifier. If any identifiers are of unique types and clash, then
        raises a ``UnresolvableReferenceDuplicateError``.

        **Returns**
        The merge operation is in-place and returns a changeset of appended identifiers
        and enhancements.

        Args:
            - self (Reference): The existing reference.
            - enhancements (list["Enhancement"]): The incoming enhancements.
            - identifiers (list["LinkedExternalIdentifier"]): The incoming identifiers.
            - duplicate_depth (int): Internal, tracks the current depth of duplication.
            - propagate_upwards (bool): Whether to propagate changes up the canonical
                duplicate_of chain.

        Returns:
            - tuple[list["LinkedExternalIdentifier"], list["Enhancement"]]: The
            changeset of appended identifiers and enhancements.

        """

        def _hash_model(obj: Enhancement | LinkedExternalIdentifier) -> str:
            """Hash enhancement or identifiers for contentwise comparison."""
            return obj.model_dump_json(
                exclude={"id", "reference_id", "reference"},
                exclude_none=True,
            )

        if duplicate_depth > settings.max_reference_duplicate_depth:
            msg = "Max duplicate depth reached."
            raise UnresolvableReferenceDuplicateError(msg)

        if not self.enhancements:
            self.enhancements = []
        if not self.identifiers:
            self.identifiers = []

        existing_enhancements = {
            _hash_model(enhancement) for enhancement in self.enhancements
        }
        existing_identifiers = {
            _hash_model(identifier) for identifier in self.identifiers
        }
        existing_unique_identifiers = {
            identifier.identifier.identifier_type
            for identifier in self.identifiers
            if identifier.identifier.unique
        }

        delta_enhancements = [
            incoming_enhancement.model_copy(
                update={
                    "id": uuid.uuid4(),
                    "reference_id": self.id,
                    "derived_from": [incoming_enhancement.id],
                }
            )
            for incoming_enhancement in enhancements or []
            if _hash_model(incoming_enhancement) not in existing_enhancements
        ]
        delta_identifiers = [
            incoming_identifier.model_copy(
                update={"id": uuid.uuid4(), "reference_id": self.id}
            )
            for incoming_identifier in identifiers or []
            if _hash_model(incoming_identifier) not in existing_identifiers
        ]
        clashing_identifiers = [
            incoming_identifier
            for incoming_identifier in delta_identifiers
            if incoming_identifier.identifier.identifier_type
            in existing_unique_identifiers
        ]

        if clashing_identifiers:
            msg = f"Clashing unique identifiers found: {clashing_identifiers}"
            raise UnresolvableReferenceDuplicateError(msg)

        self.enhancements += delta_enhancements
        self.identifiers += delta_identifiers

        # Edge case: our duplicate detection is fuzzy, allowing for small drift
        # If we have a reference A, duplicated by B, and then import a new reference
        # C, it's possible that C is detected as a duplicate of B but not A.
        # In this case, we mark C.duplicate_of=B.id, but we do propagate all of C's
        # enhancements up to A. And so on through the alphabet :)
        if self.canonical_reference and propagate_upwards:
            # We know that A has at least the same references as B so we can work
            # on the changeset only.
            self.canonical_reference.merge(
                delta_identifiers,
                delta_enhancements,
                duplicate_depth=duplicate_depth + 1,
            )

        return delta_identifiers, delta_enhancements


class LinkedExternalIdentifier(DomainBaseModel, SQLAttributeMixin):
    """External identifier model with database attributes included."""

    identifier: destiny_sdk.identifiers.ExternalIdentifier = Field(
        description="The identifier itself.", discriminator="identifier_type"
    )
    reference_id: uuid.UUID = Field(
        description="The ID of the reference this identifier identifies."
    )
    reference: Reference | None = Field(
        default=None,
        description="The reference this identifier identifies.",
    )


class GenericExternalIdentifier(DomainBaseModel):
    """
    Generic external identifier model for all subtypes.

    The identifier is casted to a string for all inheriters.
    """

    identifier: str = Field(
        description="The identifier itself.",
    )
    identifier_type: ExternalIdentifierType = Field(
        description="The type of the identifier.",
    )
    other_identifier_name: str | None = Field(
        None,
        description="The name of the other identifier.",
    )

    @classmethod
    def from_specific(
        cls,
        external_identifier: ExternalIdentifier,
    ) -> Self:
        """Create a generic external identifier from a specific implementation."""
        return cls(
            identifier=str(external_identifier.identifier),
            identifier_type=external_identifier.identifier_type,
            other_identifier_name=external_identifier.other_identifier_name
            if hasattr(external_identifier, "other_identifier_name")
            else None,
        )


class ExternalIdentifierSearch(GenericExternalIdentifier):
    """Model to search for an external identifier."""


class Enhancement(DomainBaseModel, SQLAttributeMixin):
    """Core enhancement model with database attributes included."""

    source: str = Field(
        description="The enhancement source for tracking provenance.",
    )
    visibility: Visibility = Field(
        description="The level of visibility of the enhancement"
    )
    robot_version: str | None = Field(
        default=None,
        description="The version of the robot that generated the content.",
    )
    derived_from: list[uuid.UUID] | None = Field(
        default=None,
        description="List of enhancement IDs that this enhancement was derived from.",
    )
    content: EnhancementContent = Field(
        discriminator="enhancement_type",
        description="The content of the enhancement.",
    )
    reference_id: uuid.UUID = Field(
        description="The ID of the reference this enhancement is associated with."
    )

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )


class EnhancementRequest(DomainBaseModel, SQLAttributeMixin):
    """Request to add an enhancement to a specific reference."""

    reference_id: uuid.UUID = Field(
        description="The ID of the reference this enhancement is associated with."
    )
    robot_id: uuid.UUID = Field(
        description="The robot to request the enhancement from."
    )
    source: str | None = Field(
        default=None,
        description="The source of the batch enhancement request.",
    )
    enhancement_parameters: dict | None = Field(
        default=None,
        description="Additional optional parameters to pass through to the robot.",
    )
    request_status: EnhancementRequestStatus = Field(
        default=EnhancementRequestStatus.RECEIVED,
        description="The status of the request to create an enhancement.",
    )
    error: str | None = Field(
        None,
        description="Error encountered during the enhancement process.",
    )

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )


class BatchEnhancementRequest(DomainBaseModel, SQLAttributeMixin):
    """Request to add enhancements to a list of references."""

    reference_ids: list[uuid.UUID] = Field(
        description="The IDs of the references these enhancements are associated with."
    )
    robot_id: uuid.UUID = Field(
        description="The robot to request the enhancement from."
    )
    request_status: BatchEnhancementRequestStatus = Field(
        default=BatchEnhancementRequestStatus.RECEIVED,
        description="The status of the request to create an enhancement.",
    )
    source: str | None = Field(
        default=None,
        description="The source of the batch enhancement request.",
    )
    enhancement_parameters: dict | None = Field(
        default=None,
        description="Additional optional parameters to pass through to the robot.",
    )
    error: str | None = Field(
        default=None,
        description="""
Procedural error affecting all references encountered during the enhancement process.
Errors for individual references are provided <TBC>.
""",
    )
    reference_data_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing the reference data for the robot.",
    )
    result_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing the result data from the robot.",
    )
    validation_result_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing the validation result data from the robot.",
    )

    @property
    def n_references(self) -> int:
        """The number of references in the request."""
        return len(self.reference_ids)


class BatchRobotResultValidationEntry(DomainBaseModel):
    """A single entry in the validation result file for a batch enhancement request."""

    reference_id: uuid.UUID | None = Field(
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


class RobotAutomation(DomainBaseModel, SQLAttributeMixin):
    """
    Automation model for a robot.

    This is used as a source of truth for an Elasticsearch index that percolates
    references or enhancements against the queries. If a query matches, a request
    is sent to the specified robot to perform the enhancement.
    """

    robot_id: UUID4 = Field(
        description="The ID of the robot that will be used to enhance the reference."
    )
    query: dict[str, Any] = Field(
        description="The query that will be used to match references against."
    )


class RobotAutomationPercolationResult(BaseModel):
    """Result of a percolation query against RobotAutomations."""

    robot_id: UUID4
    reference_ids: set[UUID4]
