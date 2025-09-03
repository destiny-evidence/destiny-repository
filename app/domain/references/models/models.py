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

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.base import DomainBaseModel, ProjectedBaseModel, SQLAttributeMixin
from app.persistence.blob.models import BlobStorageFile
from app.persistence.es.persistence import ESSearchResult

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


class DuplicateDetermination(StrEnum):
    """
    The determination of whether a reference is a duplicate.

    **Allowed values**:
    - `pending`: The duplicate status is still being determined.
    - `nominated`: Candidate duplicates have been identified for the reference and
        it is being further deduplicated.
    - `duplicate`: The reference is a duplicate of another reference.
    - `exact_duplicate`: The reference is an identical subset of another reference
        and has been removed. This is rare and generally occurs in repeated imports.
    - `not_duplicate`: The reference is not a duplicate of another reference.
    - `blurred_fingerprint`: The reference does contain have enough information to
        perform deduplication.
    - `unresolved`: Automatic attempts to resolve the duplicate were unsuccessful.
    - `decoupled`: The existing duplicate mapping has been changed/removed based on new
        information and the references involved require special attention.
    """

    PENDING = auto()
    NOMINATED = auto()
    DUPLICATE = auto()
    EXACT_DUPLICATE = auto()
    CANONICAL = auto()
    BLURRED_FINGERPRINT = auto()
    UNRESOLVED = auto()
    DECOUPLED = auto()

    @classmethod
    def get_terminal_states(cls) -> set["DuplicateDetermination"]:
        """Return the set of terminal DuplicateDetermination states."""
        return {
            cls.DUPLICATE,
            cls.EXACT_DUPLICATE,
            cls.CANONICAL,
            cls.BLURRED_FINGERPRINT,
            cls.UNRESOLVED,
        }


class DuplicateAction(StrEnum):
    """What to do with a duplicate reference if detected."""

    APPEND = auto()
    DISCARD = auto()


class Reference(
    DomainBaseModel,
    ProjectedBaseModel,  # References can self-project to the same structure
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

    duplicate_decision: "ReferenceDuplicateDecision | None" = Field(
        default=None,
        description="The current active duplicate decision for this reference. If None,"
        " either duplicate_decision has not been preloaded or the duplicate status"
        " is pending.",
    )

    canonical_reference: "Reference | None" = Field(
        default=None,
        description="The canonical reference that this reference is a duplicate of",
    )
    duplicate_references: list["Reference"] | None = Field(
        default=None,
        description="A list of references that this reference duplicates",
    )

    @property
    def canonical(self) -> bool | None:
        """
        Check if this reference is the canonical version.

        Returns None if no duplicate decision is present, either due to not being
        preloaded or still pending.
        """
        if not self.duplicate_decision:
            return None
        return (
            self.duplicate_decision.duplicate_determination
            == DuplicateDetermination.CANONICAL
        )

    def is_superset(
        self,
        reference: "Reference",
    ) -> bool:
        """
        Check if this Reference is a superset of the given Reference.

        This compares enhancements, identifiers and visibility, removing
        contextual differences (eg database ids), to verify if the content
        is identical.

        :param reference: The reference to compare against.
        :type reference: Reference
        :return: True if the given Reference is a subset of this Reference, else False.
        :rtype: bool
        """

        def _create_hash_set(
            objs: list[Enhancement] | list[LinkedExternalIdentifier] | None,
        ) -> set[int]:
            return {obj.hash_data() for obj in (objs or [])}

        # Find anything in the reference that is not in self
        return (
            reference.visibility != self.visibility
            or bool(
                _create_hash_set(reference.enhancements)
                - _create_hash_set(self.enhancements)
            )
            or bool(
                _create_hash_set(reference.identifiers)
                - _create_hash_set(self.identifiers)
            )
        )


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

    def hash_data(self) -> int:
        """Contentwise hash of the identifier, excluding relationships."""
        return hash(self.identifier.model_dump_json(exclude_none=True))


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

    def hash_data(self) -> int:
        """Contentwise hash of the enhancement, excluding relationships."""
        return hash(
            self.model_dump_json(
                exclude={"id", "reference_id", "reference"}, exclude_none=True
            )
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


class CandidacyFingerprint(ProjectedBaseModel):
    """
    Model representing a simplified reference fingerprint.

    This subsets Fingerprint and is used for selecting candidate pairings with
    which to do more detailed de-duplication.
    """

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
        """Whether the fingerprint has the minimum fields required for matching."""
        return all((self.publication_year, self.authors, self.title))


class CandidacyFingerprintSearchResult(BaseModel):
    """Search result for candidate fingerprints."""

    fingerprint: CandidacyFingerprint
    candidate_duplicates: list[ESSearchResult]


class Fingerprint(CandidacyFingerprint):
    """
    Model representing a reference fingerprint.

    A fingerprint is a flattened representation of a reference, including all relevant
    data for de-duplication. This data may or may not be pre-processed, eg
    normalisation.
    """

    doi_identifier: str | None = Field(
        default=None,
        description="The DOI identifier of the reference.",
    )
    openalex_identifier: str | None = Field(
        default=None,
        description="The OpenAlex identifier of the reference.",
    )
    pubmed_identifier: int | None = Field(
        default=None,
        description="The PubMed identifier of the reference.",
    )
    other_identifiers: dict[str, str] = Field(
        default_factory=dict,
        description="Other identifiers for the reference.",
    )
    publisher: str | None = Field(
        default=None,
        description="The publisher of the reference.",
    )
    abstract: str | None = Field(
        default=None,
        description="The abstract of the reference.",
    )


class ReferenceDuplicateDecision(DomainBaseModel, SQLAttributeMixin):
    """Model representing a decision on whether a reference is a duplicate."""

    reference_id: UUID4 = Field(description="The ID of the reference being evaluated.")
    enhancement_id: UUID4 | None = Field(
        default=None,
        description="The ID of the enhancement triggering the evaluation. "
        "If None, the decision is from an import not an enhancement.",
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
    fingerprint: Fingerprint = Field(
        description="The fingerprint of the reference being evaluated."
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
