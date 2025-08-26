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
from app.core.exceptions import UnresolvableReferenceDuplicateError, WrongReferenceError
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


class IngestionProcess(StrEnum):
    """The process used to create or modify a reference."""

    IMPORT = auto()
    ROBOT_ENHANCEMENT = auto()


class DuplicateDetermination(StrEnum):
    """
    The determination of whether a reference is a duplicate.

    **Allowed values**:
    - `pending`: The duplicate status is still being determined.
    - `duplicate`: The reference is a duplicate of another reference.
    - `not_duplicate`: The reference is not a duplicate of another reference.
    - `unresolved`: Automatic attempts to resolve the duplicate were unsuccessful.
    """

    PENDING = auto()
    DUPLICATE = auto()
    NOT_DUPLICATE = auto()
    UNRESOLVED = auto()


class DuplicateAction(StrEnum):
    """What to do with a duplicate reference if detected."""

    APPEND = auto()
    DISCARD = auto()


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
        propagate: bool,
    ) -> tuple[list["LinkedExternalIdentifier"], list["Enhancement"]]:
        """
        Merge reference details into this reference.

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
                Only applicable when propagate=True.
            - propagate (bool): If True, incoming enhancements and identifiers will be
                copied before merging (updating the ID and creating a ``derived_from``
                relationship) and propagated recursively to the canonical reference(s).
                If False, the incoming enhancements and identifiers will be merged onto
                the current reference without modification. In general we propagate on
                imports, and not on new enhancements from robots.

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

        if propagate:
            delta_enhancements = [
                incoming_enhancement.model_copy(
                    update={
                        "id": uuid.uuid4(),
                        "reference_id": self.id,
                        "derived_from": [incoming_enhancement.id],
                    }
                )
                for incoming_enhancement in enhancements
                if _hash_model(incoming_enhancement) not in existing_enhancements
            ]
            delta_identifiers = [
                incoming_identifier.model_copy(
                    update={"id": uuid.uuid4(), "reference_id": self.id}
                )
                for incoming_identifier in identifiers
                if _hash_model(incoming_identifier) not in existing_identifiers
            ]
        else:
            # Verify reference IDs
            delta_enhancements = [
                incoming_enhancement
                for incoming_enhancement in enhancements
                if _hash_model(incoming_enhancement) not in existing_enhancements
            ]
            delta_identifiers = [
                incoming_identifier
                for incoming_identifier in identifiers
                if _hash_model(incoming_identifier) not in existing_identifiers
            ]
            if not all(
                obj.reference_id == self.id
                for obj in delta_enhancements + delta_identifiers
            ):
                detail = f"Incoming data is for a different reference than {self.id}."
                raise WrongReferenceError(detail)

        self.enhancements += delta_enhancements
        self.identifiers += delta_identifiers

        # Edge case: our duplicate detection is fuzzy, allowing for small drift
        # If we have a reference A, duplicated by B, and then import a new reference
        # C, it's possible that C is detected as a duplicate of B but not A.
        # In this case, we mark C.duplicate_of=B.id, but we do propagate all of C's
        # enhancements up to A.
        if (
            self.canonical_reference
            and propagate
            and (delta_enhancements or delta_identifiers)
        ):
            # We know that A has at least the same references as B so we can work
            # on the changeset only.
            self.canonical_reference.merge(
                delta_identifiers,
                delta_enhancements,
                duplicate_depth=duplicate_depth + 1,
                propagate=propagate,
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
    def matchable(self) -> bool:
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
    source: IngestionProcess = Field(
        description="The process that triggered this decision.",
    )
    source_id: UUID4 | None = Field(
        default=None,
        description="The ID of the source that triggered this decision. Provides "
        "provenance in combination with the ``source`` field.",
    )
    candidate_duplicate_ids: list[UUID4] = Field(
        default_factory=list,
        description="A list of candidate duplicate IDs for the reference.",
    )
    duplicate_determination: DuplicateDetermination = Field(
        default=DuplicateDetermination.PENDING,
        description="The duplicate status of the reference.",
    )
    fingerprint: Fingerprint = Field(
        description="The fingerprint of the reference being evaluated."
    )

    reference: Reference | None = Field(
        default=None, description="The reference being evaluated."
    )
