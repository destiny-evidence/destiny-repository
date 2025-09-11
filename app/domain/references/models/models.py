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
    model_validator,
)

from app.core.telemetry.logger import get_logger
from app.domain.base import DomainBaseModel, ProjectedBaseModel, SQLAttributeMixin
from app.domain.imports.models.models import CollisionStrategy
from app.persistence.blob.models import BlobStorageFile

logger = get_logger(__name__)

ExternalIdentifierAdapter: TypeAdapter[ExternalIdentifier] = TypeAdapter(
    ExternalIdentifier,
)


class EnhancementRequestStatus(StrEnum):
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


class DuplicateDetermination(StrEnum):
    """
    The determination of whether a reference is a duplicate.

    This encodes both a status and a determination.

    **Allowed values**:
    - `pending`: The duplicate status is still being determined.
    - `nominated`: Candidate duplicates have been identified for the reference and
        it is being further deduplicated.
    - `duplicate`: The reference is a duplicate of another reference.
    - `exact_duplicate`: The reference is an identical subset of another reference
        and has been removed. This is rare and generally occurs in repeated imports.
    - `canonical`: The reference is not a duplicate of another reference.
    - `unresolved`: Automatic attempts to resolve the duplicate were unsuccessful.
    - `decoupled`: The existing duplicate mapping has been changed/removed based on new
        information and the references involved require special attention.
    """

    PENDING = auto()
    NOMINATED = auto()
    DUPLICATE = auto()
    EXACT_DUPLICATE = auto()
    CANONICAL = auto()
    UNRESOLVED = auto()
    DECOUPLED = auto()

    @classmethod
    def get_terminal_states(cls) -> set["DuplicateDetermination"]:
        """Return the set of terminal DuplicateDetermination states."""
        return {
            cls.DUPLICATE,
            cls.EXACT_DUPLICATE,
            cls.CANONICAL,
            cls.UNRESOLVED,
            cls.DECOUPLED,
        }


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

    async def merge(  # noqa: PLR0912
        self,
        incoming_reference: Self,
        collision_strategy: CollisionStrategy,
    ) -> None:
        """
        Merge an incoming reference into this one.

        Args:
            - existing_reference (Reference): The existing reference.
            - incoming_reference (Reference): The incoming reference.
            - collision_strategy (CollisionStrategy): The strategy to use for
                handling collisions.

        Returns:
            - Reference: The final reference to be persisted.

        """

        def _get_identifier_key(
            identifier: ExternalIdentifier,
        ) -> tuple[str, str | None]:
            """
            Get the key for an identifier.

            Args:
                - identifier (LinkedExternalIdentifier)

            Returns:
                - tuple[str, str | None]: The key for the identifier.

            """
            return (
                identifier.identifier_type,
                identifier.other_identifier_name
                if hasattr(identifier, "other_identifier_name")
                else None,
            )

        # Graft matching IDs from self to incoming
        for identifier in incoming_reference.identifiers or []:
            for existing_identifier in self.identifiers or []:
                if _get_identifier_key(identifier.identifier) == _get_identifier_key(
                    existing_identifier.identifier
                ):
                    identifier.id = existing_identifier.id
        for enhancement in incoming_reference.enhancements or []:
            for existing_enhancement in self.enhancements or []:
                if (enhancement.content.enhancement_type, enhancement.source) == (
                    existing_enhancement.content.enhancement_type,
                    existing_enhancement.source,
                ):
                    enhancement.id = existing_enhancement.id

        if not self.identifiers or not incoming_reference.identifiers:
            msg = "No identifiers found in merge. This should not happen."
            raise RuntimeError(msg)

        self.enhancements = self.enhancements or []
        incoming_reference.enhancements = incoming_reference.enhancements or []

        # Merge identifiers
        if collision_strategy == CollisionStrategy.MERGE_DEFENSIVE:
            self.identifiers.extend(
                [
                    identifier
                    for identifier in incoming_reference.identifiers
                    if _get_identifier_key(identifier.identifier)
                    not in {
                        _get_identifier_key(identifier.identifier)
                        for identifier in self.identifiers
                    }
                ]
            )
        elif collision_strategy in (
            CollisionStrategy.MERGE_AGGRESSIVE,
            CollisionStrategy.OVERWRITE,
            CollisionStrategy.APPEND,
        ):
            self.identifiers = [
                identifier
                for identifier in self.identifiers
                if _get_identifier_key(identifier.identifier)
                not in {
                    _get_identifier_key(identifier.identifier)
                    for identifier in incoming_reference.identifiers
                }
            ] + incoming_reference.identifiers

        # On an overwrite, we don't preserve the existing enhancements, only identifiers
        if collision_strategy == CollisionStrategy.OVERWRITE:
            self.enhancements = incoming_reference.enhancements.copy()
            return

        # Otherwise, merge enhancements
        if collision_strategy == CollisionStrategy.APPEND:
            self.enhancements += incoming_reference.enhancements
        elif collision_strategy == CollisionStrategy.MERGE_DEFENSIVE:
            self.enhancements.extend(
                [
                    enhancement
                    for enhancement in incoming_reference.enhancements
                    if (enhancement.content.enhancement_type, enhancement.source)
                    not in {
                        (enhancement.content.enhancement_type, enhancement.source)
                        for enhancement in self.enhancements
                    }
                ]
            )
        elif collision_strategy == CollisionStrategy.MERGE_AGGRESSIVE:
            self.enhancements = [
                enhancement
                for enhancement in self.enhancements
                if (enhancement.content.enhancement_type, enhancement.source)
                not in {
                    (enhancement.content.enhancement_type, enhancement.source)
                    for enhancement in incoming_reference.enhancements
                }
            ] + incoming_reference.enhancements

        return


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
    """Request to add enhancements to a list of references."""

    reference_ids: list[uuid.UUID] = Field(
        description="The IDs of the references these enhancements are associated with."
    )
    robot_id: uuid.UUID = Field(
        description="The robot to request the enhancement from."
    )
    request_status: EnhancementRequestStatus = Field(
        default=EnhancementRequestStatus.RECEIVED,
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


class RobotResultValidationEntry(DomainBaseModel):
    """A single entry in the validation result file for a enhancement request."""

    reference_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The ID of the reference which was enhanced. "
            "If this is empty, the EnhancementResultEntry could not be parsed."
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


class CandidateDuplicateSearchFields(ProjectedBaseModel):
    """Model representing fields used for candidate selection."""

    publication_year: int | None = Field(
        default=None,
        description="The publication year of the reference.",
    )
    authors: list[str] = Field(
        default_factory=list, description="The authors of the reference."
    )
    title: str | None = Field(
        default=None,
        description="The title of the reference.",
    )

    @property
    def searchable(self) -> bool:
        """Whether the projection has the minimum fields required for matching."""
        return all((self.publication_year, self.authors, self.title))


class ReferenceDuplicateDecision(DomainBaseModel, SQLAttributeMixin):
    """Model representing a decision on whether a reference is a duplicate."""

    reference_id: UUID4 = Field(description="The ID of the reference being evaluated.")
    enhancement_id: UUID4 | None = Field(
        default=None,
        description=(
            "The ID of the enhancement that triggered this duplicate decision, if any."
        ),
    )
    active_decision: bool = Field(
        default=False,
        description="Whether this is the active decision for the reference.",
    )
    candidate_duplicate_ids: list[UUID4] = Field(
        default_factory=list,
        description="A list of candidate duplicate IDs for the reference.",
    )
    duplicate_determination: DuplicateDetermination = Field(
        default=DuplicateDetermination.PENDING,
        description="The duplicate status of the reference.",
    )
    canonical_reference_id: UUID4 | None = Field(
        default=None,
        description="The ID of the canonical reference this reference duplicates.",
    )

    @model_validator(mode="after")
    def check_canonical_reference_id_populated_iff_duplicate(self) -> Self:
        """Assert that canonical must exist if and only if decision is duplicate."""
        if (
            self.canonical_reference_id
            is not None
            == self.duplicate_determination
            in (
                DuplicateDetermination.DUPLICATE,
                DuplicateDetermination.EXACT_DUPLICATE,
            )
        ):
            msg = (
                "canonical_reference_id must be populated if and only if "
                "duplicate_determination is DUPLICATE or EXACT_DUPLICATE"
            )
            raise ValueError(msg)

        return self
