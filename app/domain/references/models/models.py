"""Models associated with references."""

import uuid
from enum import StrEnum, auto
from typing import Any, Literal, Self

import destiny_sdk

# Explicitly import these models for easy use in the rest of the codebase
from destiny_sdk.enhancements import EnhancementContent, EnhancementType  # noqa: F401
from destiny_sdk.identifiers import ExternalIdentifier, ExternalIdentifierType
from pydantic import (
    UUID4,
    BaseModel,
    Field,
    PositiveInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.core.telemetry.logger import get_logger
from app.domain.base import (
    DomainBaseModel,
    ProjectedBaseModel,
    SQLAttributeMixin,
    SQLTimestampMixin,
)
from app.persistence.blob.models import BlobStorageFile

logger = get_logger(__name__)

ExternalIdentifierAdapter: TypeAdapter[ExternalIdentifier] = TypeAdapter(
    ExternalIdentifier,
)


class EnhancementRequestStatus(StrEnum):
    """The status of an enhancement request."""

    RECEIVED = auto()
    """Enhancement request has been received by the repo."""
    ACCEPTED = auto()
    """Enhancement request has been accepted by the robot."""
    PROCESSING = auto()
    """Enhancement request is being processed by the robot."""
    REJECTED = auto()
    """Enhancement request has been rejected by the robot."""
    PARTIAL_FAILED = auto()
    """Some enhancements failed to create."""
    FAILED = auto()
    """All enhancements failed to create."""
    IMPORTING = auto()
    """Enhancements have been received by the repo and are being imported."""
    INDEXING = auto()
    """Enhancements have been imported and are being indexed."""
    INDEXING_FAILED = auto()
    """Enhancements have been imported but indexing failed."""
    COMPLETED = auto()
    """All enhancements have been created."""


class Visibility(StrEnum):
    """
    The visibility of a data element in the repository.

    This is used to manage whether information should be publicly available or
    restricted (generally due to copyright constraints from publishers).

    TODO: Implement data governance layer to manage this.
    """

    PUBLIC = auto()
    """Visible to the general public without authentication."""
    RESTRICTED = auto()
    """Requires authentication to be visible."""
    HIDDEN = auto()
    """Is not visible, but may be passed to data mining processes."""


class DuplicateDetermination(StrEnum):
    """
    The determination of whether a reference is a duplicate.

    This encodes both a status and a determination.
    """

    PENDING = auto()
    """The duplicate status is still being determined."""
    NOMINATED = auto()
    """
    Candidate canonicals have been identified for the reference and it is being
    further deduplicated.
    """
    DUPLICATE = auto()
    """[TERMINAL] The reference is a duplicate of another reference."""
    EXACT_DUPLICATE = auto()
    """
    [TERMINAL] The reference is an identical subset of another reference and has been
    removed. This is rare and generally occurs in repeated imports.
    """
    CANONICAL = auto()
    """[TERMINAL] The reference is not a duplicate of another reference."""
    UNRESOLVED = auto()
    """Automatic attempts to resolve the duplicate were unsuccessful."""
    UNSEARCHABLE = auto()
    """
    [TERMINAL] The reference does not have sufficient metadata to be
    automatically matched to other references, or the duplicate detection
    process has been explicitly disabled.
    """
    DECOUPLED = auto()
    """
    A decision has been made, but needs further attention. This could
    be due to a change in the canonical mapping, or a chain of duplicates longer
    than allowed.
    """

    @classmethod
    def get_terminal_states(cls) -> set["DuplicateDetermination"]:
        """Return the set of terminal DuplicateDetermination states."""
        return {
            cls.DUPLICATE,
            cls.EXACT_DUPLICATE,
            cls.CANONICAL,
            cls.UNSEARCHABLE,
        }


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
        Pessimistically check if this reference is the canonical version.

        Returns None if no duplicate decision is present, either due to not being
        preloaded or still pending.
        """
        if not self.duplicate_decision:
            return None
        return (
            self.duplicate_decision.duplicate_determination
            == DuplicateDetermination.CANONICAL
        )

    @property
    def canonical_like(self) -> bool:
        """
        Optimistically check if this reference is the canonical version.

        Only returns False if the reference is a determined duplicate. Pending,
        unresolved and not-preloaded duplicate decisions are treated as canonical-like.
        """
        if not self.duplicate_decision:
            return True
        return (
            self.duplicate_decision.duplicate_determination
            != DuplicateDetermination.DUPLICATE
        )

    @property
    def canonical_chain_length(self) -> int:
        """
        Get the length of the canonical chain for this reference.

        This is the number of references in the chain from this reference to
        the root canonical reference, including this reference.

        Requires canonical_reference to be preloaded, will always return 1 if not.
        """
        return 1 + (
            self.canonical_reference.canonical_chain_length
            if self.canonical_reference
            else 0
        )

    def is_superset(
        self,
        reference: "Reference",
    ) -> bool:
        """
        Check if this Reference is a superset of the given Reference.

        This compares enhancements, identifiers and visibility, removing
        persistence differences (eg database ids), to verify if the content
        is identical. If the given Reference has *anything* unique, this will
        return False.

        :param reference: The reference to compare against.
        :type reference: Reference
        :return: True if the given Reference is a subset of this Reference, else False.
        :rtype: bool
        """

        def _supersets(
            superset: list[Enhancement] | list[LinkedExternalIdentifier] | None,
            subset: list[Enhancement] | list[LinkedExternalIdentifier] | None,
        ) -> bool:
            """Return True if superset contains all elements of subset."""
            return {obj.hash_data() for obj in (superset or [])} >= {
                obj.hash_data() for obj in (subset or [])
            }

        # Find anything in the reference that is not in self
        return (
            reference.visibility == self.visibility
            and _supersets(self.enhancements, reference.enhancements)
            and _supersets(self.identifiers, reference.identifiers)
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
    identifier_type: ExternalIdentifierType | None = Field(
        description="The type of the identifier. If None, identifier is a database id.",
    )
    other_identifier_name: str | None = Field(
        default=None,
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


class IdentifierLookup(GenericExternalIdentifier):
    """Model to search for an external identifier."""


class Enhancement(DomainBaseModel, SQLTimestampMixin):
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
        """
        Contentwise hash of the enhancement.

        Excludes relationships and timestamps.
        """
        return hash(
            self.model_dump_json(
                exclude={"id", "reference_id", "reference", "created_at", "updated_at"},
                exclude_none=True,
            )
        )


class EnhancementRequest(DomainBaseModel, ProjectedBaseModel, SQLAttributeMixin):
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
    pending_enhancements: list["PendingEnhancement"] | None = Field(
        default=None,
        description="List of pending enhancements for the request.",
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


class CandidateCanonicalSearchFields(ProjectedBaseModel):
    """
    Fields used for candidate canonical selection.

    The search implementation lives at
    :attr:`app.domain.references.repository.ReferenceESRepository.search_for_candidate_canonicals`.
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
    def is_searchable(self) -> bool:
        """Whether the projection has the fields required to search for candidates."""
        return all((self.publication_year, self.authors, self.title))


class ReferenceSearchFields(ProjectedBaseModel):
    """
    Projection representing fields used for searching references.

    This model is a projection of
    :class:`app.domain.references.models.models.Reference`.

    This is injected into the root of Elasticsearch Reference documents for easy
    searching.
    """

    abstract: str | None = Field(
        default=None, description="The abstract of the reference."
    )

    authors: list[str] = Field(
        default_factory=list, description="The authors of the reference."
    )

    publication_year: int | None = Field(
        default=None,
        description="The publication year of the reference.",
    )

    title: str | None = Field(
        default=None,
        description="The title of the reference.",
    )

    annotations: list[str] = Field(
        default_factory=list,
        description=(
            "List of true annotations on the reference."
            "Each annotation is in the format `<scheme>/<label>`."
        ),
    )

    evaluated_schemes: list[str] = Field(
        default_factory=list,
        description=(
            "List of annotation schemes that have been evaluated on the reference."
        ),
    )

    destiny_inclusion_score: float | None = Field(
        default=None,
        description=(
            "The inclusion score on the destiny domain inclusion annotation, "
            "if evaluated."
        ),
    )

    def to_canonical_candidate_search_fields(self) -> CandidateCanonicalSearchFields:
        """Return fields needed for candidate canonical selection."""
        return CandidateCanonicalSearchFields(
            publication_year=self.publication_year,
            authors=self.authors,
            title=self.title,
        )

    @classmethod
    def _normalise_string(cls, value: str) -> str:
        """Normalise string fields by stripping whitespace."""
        return value.strip()

    @field_validator("abstract", "title", mode="after")
    @classmethod
    def normalise_string_validator(cls, value: str | None) -> str | None:
        """Normalise string fields by stripping whitespace."""
        if not value:
            return value
        return cls._normalise_string(value)

    @field_validator("authors", "annotations", "evaluated_schemes", mode="after")
    @classmethod
    def normalise_string_list_validator(cls, value: list[str]) -> list[str]:
        """Normalise string list fields by stripping whitespace."""
        return [cls._normalise_string(v) for v in value if v]


class ReferenceDuplicateDeterminationResult(BaseModel):
    """Model representing the result of a duplicate determination."""

    duplicate_determination: Literal[
        DuplicateDetermination.CANONICAL,
        DuplicateDetermination.DUPLICATE,
        DuplicateDetermination.UNRESOLVED,
        DuplicateDetermination.UNSEARCHABLE,
    ]
    canonical_reference_id: UUID4 | None = Field(
        default=None,
        description="The ID of the determined canonical reference.",
    )
    detail: str | None = Field(
        default=None,
        description="Optional detail about the determination process, particularly"
        " where the determination is UNRESOLVED or UNSEARCHABLE.",
    )

    @model_validator(mode="after")
    def check_canonical_reference_id_populated_iff_duplicate(self) -> Self:
        """Assert that canonical must exist if and only if decision is duplicate."""
        if (self.canonical_reference_id is not None) != (
            self.duplicate_determination == DuplicateDetermination.DUPLICATE
        ):
            msg = (
                "canonical_reference_id must be populated if and only if "
                "duplicate_determination is DUPLICATE"
            )
            raise ValueError(msg)

        return self


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
    candidate_canonical_ids: list[UUID4] = Field(
        default_factory=list,
        description="A list of candidate canonical IDs for the reference.",
    )
    duplicate_determination: DuplicateDetermination = Field(
        default=DuplicateDetermination.PENDING,
        description="The duplicate status of the reference.",
    )
    canonical_reference_id: UUID4 | None = Field(
        default=None,
        description="The ID of the canonical reference this reference duplicates.",
    )
    detail: str | None = Field(
        default=None,
        description="Optional additional detail about the decision.",
    )

    @model_validator(mode="after")
    def check_canonical_reference_id_populated_iff_duplicate(self) -> Self:
        """Assert that canonical must exist if and only if decision is duplicate."""
        if self.duplicate_determination == DuplicateDetermination.DECOUPLED:
            # Allow ambiguous state for decoupled decisions as they are complex,
            # requiring human intervention.
            return self
        if (self.canonical_reference_id is not None) != (
            self.duplicate_determination
            in (
                DuplicateDetermination.DUPLICATE,
                DuplicateDetermination.EXACT_DUPLICATE,
            )
        ):
            msg = (
                "canonical_reference_id must be populated if and only if "
                "duplicate_determination is DUPLICATE, EXACT_DUPLICATE"
                " or DECOUPLED"
            )
            raise ValueError(msg)

        return self

    @model_validator(mode="after")
    def check_active_decision_is_terminal(self) -> Self:
        """Assert that active decisions are only set for terminal states."""
        if (
            self.active_decision
            and self.duplicate_determination
            not in DuplicateDetermination.get_terminal_states()
        ):
            msg = (
                "Decision can only be active if terminal: "
                f"{self.duplicate_determination}"
            )
            raise ValueError(msg)

        return self


class ReferenceWithChangeset(Reference):
    """Reference model with a changeset included."""

    changeset: Reference = Field(
        description=(
            "The changeset that was applied to the reference. This is purely additive."
        )
    )


class PendingEnhancementStatus(StrEnum):
    """
    The status of a pending enhancement.

    **Allowed values**:
    - `pending`: Enhancement is waiting to be processed.
    - `accepted`: Enhancement has been accepted for processing.
    - `importing`: Enhancement is currently being imported.
    - `indexing`: Enhancement is currently being indexed.
    - `indexing_failed`: Enhancement indexing has failed.
    - `discarded`: Enhancement has been discarded as an exact duplicate.
    - `completed`: Enhancement has been processed successfully.
    - `failed`: Enhancement processing has failed.
    """

    PENDING = auto()
    ACCEPTED = auto()
    IMPORTING = auto()
    INDEXING = auto()
    INDEXING_FAILED = auto()
    DISCARDED = auto()
    COMPLETED = auto()
    FAILED = auto()


class PendingEnhancement(DomainBaseModel, SQLAttributeMixin):
    """A pending enhancement."""

    reference_id: UUID4 = Field(
        ...,
        description="The ID of the reference to be enhanced.",
    )
    robot_id: UUID4 = Field(
        ...,
        description="The ID of the robot that will perform the enhancement.",
    )
    enhancement_request_id: UUID4 | None = Field(
        default=None,
        description=(
            "The ID of the batch enhancement request that this pending enhancement"
            " belongs to."
        ),
    )
    robot_enhancement_batch_id: UUID4 | None = Field(
        default=None,
        description=(
            "The ID of the robot enhancement batch that this pending enhancement"
            " belongs to."
        ),
    )
    status: PendingEnhancementStatus = Field(
        default=PendingEnhancementStatus.PENDING,
        description="The status of the pending enhancement.",
    )
    source: str | None = Field(
        default=None,
        description=(
            "The source of the pending enhancement for provenance tracking, "
            "if not an enhancement request."
        ),
    )

    @model_validator(mode="after")
    def check_enhancement_request_or_source_present(self) -> Self:
        """Ensure either enhancement request ID or source is present."""
        if not (self.enhancement_request_id or self.source):
            msg = "Either enhancement_request_id or source must be present."
            raise ValueError(msg)

        return self


class RobotEnhancementBatch(DomainBaseModel, SQLAttributeMixin):
    """A batch of references to be enhanced by a robot."""

    robot_id: UUID4 = Field(
        ...,
        description="The ID of the robot that will perform the enhancement.",
    )
    reference_data_file: BlobStorageFile | None = Field(
        None,
        description="The file containing the references to be enhanced.",
    )
    result_file: BlobStorageFile | None = Field(
        None,
        description="The file containing the enhancement results.",
    )
    validation_result_file: BlobStorageFile | None = Field(
        default=None,
        description="The file containing validation result data from the repository.",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement batch process.",
    )
    pending_enhancements: list[PendingEnhancement] | None = Field(
        default=None,
        description="The pending enhancements in this batch.",
    )


class ReferenceIds(BaseModel):
    """Model representing a list of reference IDs."""

    reference_ids: list[UUID4] = Field(
        ...,
        description="A list of reference IDs.",
    )


class PublicationYearRange(BaseModel):
    """A range of publication years for filtering search results."""

    start: PositiveInt | None = Field(
        None,
        description="Start year (inclusive)",
    )
    end: PositiveInt | None = Field(
        None,
        description="End year (inclusive)",
    )

    @model_validator(mode="after")
    def validate_end_ge_start(self) -> Self:
        """Validate that end year is greater than or equal to start year."""
        if self.start and self.end and self.end < self.start:
            msg = "End year must be greater than or equal to start year."
            raise ValueError(msg)
        return self


class AnnotationFilter(BaseModel):
    """Model representing an annotation filter for searching references."""

    scheme: str = Field(description="The annotation scheme to filter on.")
    label: str | None = Field(
        description="The annotation label to filter on.", default=None
    )
    score: float | None = Field(
        default=None,
        description="Optional score threshold for the annotation filter.",
        ge=0.0,
        le=1.0,
    )
