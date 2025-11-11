"""Objects used to interface with Elasticsearch implementations."""

import datetime
from typing import Any, Self
from uuid import UUID

from elasticsearch.dsl import (
    Boolean,
    Date,
    InnerDoc,
    Integer,
    Keyword,
    Nested,
    Object,
    Percolator,
    Text,
    mapped_field,
)

from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    EnhancementType,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    ReferenceSearchFields,
    ReferenceWithChangeset,
    RobotAutomation,
    Visibility,
)
from app.domain.references.models.projections import (
    ReferenceSearchFieldsProjection,
)
from app.persistence.es.persistence import (
    GenericESPersistence,
)


class ExternalIdentifierDocument(InnerDoc):
    """Persistence model for external identifiers in Elasticsearch."""

    reference_id: UUID = mapped_field(Keyword(required=True))
    identifier: str = mapped_field(Text(required=True))
    identifier_type: ExternalIdentifierType = mapped_field(Keyword(required=True))
    other_identifier_name: str | None = mapped_field(Keyword())

    @classmethod
    def from_domain(cls, domain_obj: LinkedExternalIdentifier) -> Self:
        """Create a persistence model from a domain ExternalIdentifier object."""
        return cls(
            reference_id=domain_obj.reference_id,
            identifier_type=domain_obj.identifier.identifier_type,
            identifier=str(domain_obj.identifier.identifier),
            other_identifier_name=getattr(
                domain_obj.identifier, "other_identifier_name", None
            ),
        )

    def to_domain(self, reference_id: UUID) -> LinkedExternalIdentifier:
        """Convert the persistence model into a Domain ExternalIdentifier object."""
        return LinkedExternalIdentifier(
            reference_id=self.reference_id or reference_id,
            identifier=ExternalIdentifierAdapter.validate_python(
                {
                    "identifier": self.identifier,
                    "identifier_type": self.identifier_type,
                    "other_identifier_name": self.other_identifier_name,
                }
            ),
        )


class AnnotationDocument(InnerDoc):
    """Persistence model for useful annotation fields in Elasticsearch."""

    scheme: str = mapped_field(Keyword())
    label: str = mapped_field(Keyword())
    annotation_type: str = mapped_field(Keyword())
    value: bool | None = mapped_field(Boolean(required=False))

    class Meta:
        """Allow unmapped fields in the document."""

        dynamic = True


class EnhancementContentDocument(InnerDoc):
    """
    Persistence model for enhancement content in Elasticsearch.

    We define anything we want to explicitly index here and map as dynamic in the
    parent document.
    """

    enhancement_type: EnhancementType = mapped_field(Keyword(required=True, index=True))
    annotations: list[AnnotationDocument] | None = mapped_field(
        Nested(AnnotationDocument, required=False)
    )

    class Meta:
        """Allow unmapped fields in the document."""

        dynamic = True


class EnhancementDocument(InnerDoc):
    """Persistence model for enhancements in Elasticsearch."""

    id: UUID = mapped_field(Keyword(required=True, index=True))
    reference_id: UUID = mapped_field(Keyword(required=True))
    visibility: Visibility = mapped_field(Keyword(required=True))
    source: str = mapped_field(Keyword(required=True))
    robot_version: str | None = mapped_field(Keyword())

    # We'd like to make this required after we've done a repair
    created_at: datetime.datetime | None = mapped_field(
        Date(required=False, default_timezone=datetime.UTC)
    )

    content: EnhancementContentDocument = mapped_field(
        Object(EnhancementContentDocument, required=True)
    )

    @classmethod
    def from_domain(cls, domain_obj: Enhancement) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            id=domain_obj.id,
            reference_id=domain_obj.reference_id,
            visibility=domain_obj.visibility,
            source=domain_obj.source,
            robot_version=domain_obj.robot_version,
            created_at=domain_obj.created_at,
            content=EnhancementContentDocument(
                **domain_obj.content.model_dump(mode="json")
            ),
        )

    def to_domain(self, reference_id: UUID) -> Enhancement:
        """Create a domain model from this persistence model."""
        return Enhancement(
            id=self.id,
            reference_id=self.reference_id or reference_id,
            visibility=self.visibility,
            source=self.source,
            enhancement_type=self.content.enhancement_type,
            robot_version=self.robot_version,
            created_at=self.created_at,
            content=self.content.to_dict(),
        )


class ReferenceDomainMixin(InnerDoc):
    """Mapping of Reference domain model to Elasticsearch document."""

    visibility: Visibility = mapped_field(Keyword(required=True))
    identifiers: list[ExternalIdentifierDocument] = mapped_field(
        Nested(ExternalIdentifierDocument)
    )
    enhancements: list[EnhancementDocument] = mapped_field(Nested(EnhancementDocument))
    # Active duplicate determination, if any. This will only ever present a terminal
    # state or None
    duplicate_determination: DuplicateDetermination | None = mapped_field(
        Keyword(required=False),
    )

    @classmethod
    def from_domain(cls, reference: Reference) -> Self:
        """Create a ReferenceDomainMixin from a Reference domain model."""
        return cls(
            visibility=reference.visibility,
            identifiers=[
                ExternalIdentifierDocument.from_domain(identifier)
                for identifier in reference.identifiers or []
            ],
            enhancements=[
                EnhancementDocument.from_domain(enhancement)
                for enhancement in reference.enhancements or []
            ],
            duplicate_determination=reference.duplicate_decision.duplicate_determination
            if reference.duplicate_decision
            else None,
        )

    def to_domain(self) -> Reference:
        """Create a domain model from a ReferenceDomainMixin."""
        # Passing in reference_id for back-compatibility with existing data
        # Once all references have been re-indexed, this can be removed
        reference_id = UUID(self.meta.id)
        return Reference(
            id=reference_id,
            visibility=self.visibility,
            identifiers=[
                identifier.to_domain(reference_id) for identifier in self.identifiers
            ],
            enhancements=[
                enhancement.to_domain(reference_id) for enhancement in self.enhancements
            ],
        )


class ReferenceSearchFieldsMixin(InnerDoc):
    """
    Mixin to project Reference fields relevant to various search strategies.

    Currently this holds fields for identifing candidate canonicals during deduplication
    and for searching references by query on title, authors, and abstracts.
    """

    abstract: str | None = mapped_field(Text(required=False), default=None)

    authors: list[str] | None = mapped_field(
        Text(required=False),
        default=None,
    )

    publication_year: int | None = mapped_field(
        Integer(required=False),
        default=None,
    )

    title: str | None = mapped_field(Text(required=False), default=None)

    @classmethod
    def from_projection(cls, projection: ReferenceSearchFields) -> Self:
        """Create a ReferenceCandidateCanonicalMixin from the search projection."""
        return cls(
            abstract=projection.abstract,
            title=projection.title,
            authors=projection.authors,
            publication_year=projection.publication_year,
        )

    @classmethod
    def from_domain(cls, reference: Reference) -> Self:
        """Create the ES ReferenceDeduplicationMixin."""
        return cls.from_projection(
            ReferenceSearchFieldsProjection.get_from_reference(reference)
        )


class ReferenceDocument(
    GenericESPersistence[Reference],
    ReferenceDomainMixin,
    ReferenceSearchFieldsMixin,
):
    """Persistence model for references in Elasticsearch."""

    class Index:
        """Index metadata for the persistence model."""

        name = "reference"

    @classmethod
    def from_domain(cls, domain_obj: Reference) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            # Parent's parent does accept meta, but mypy doesn't like it here.
            # Ignoring easier than chaining __init__ methods IMO.
            meta={"id": domain_obj.id},  # type: ignore[call-arg]
            **ReferenceDomainMixin.from_domain(domain_obj).to_dict(),
            **ReferenceSearchFieldsMixin.from_domain(domain_obj).to_dict(),
        )

    def to_domain(self) -> Reference:
        """Create a domain model from this persistence model."""
        return ReferenceDomainMixin.to_domain(self)


class RobotAutomationPercolationDocument(GenericESPersistence[RobotAutomation]):
    """
    Persistence model for robot automation percolation in Elasticsearch.

    This model serves two purposes in order to fully define the index: a persistence
    layer for queries that dictate robot automation, and a percolator layer to convert
    domain models to queryable documents that run against said queries.
    """

    class Index:
        """Index metadata for the persistence model."""

        name = "robot-automation-percolation"

    query: dict[str, Any] | None = mapped_field(
        Percolator(required=False),
    )
    robot_id: UUID | None = mapped_field(
        Keyword(required=False),
    )
    reference: ReferenceDomainMixin | None = mapped_field(
        Object(ReferenceDomainMixin, required=False),
    )
    changeset: ReferenceDomainMixin | None = mapped_field(
        Object(ReferenceDomainMixin, required=False),
    )

    @classmethod
    def from_domain(cls, domain_obj: RobotAutomation) -> Self:
        """Create a percolator query from a domain model."""
        return cls(
            # Parent's parent does accept meta, but mypy doesn't like it here.
            # Ignoring easier than chaining __init__ methods IMO.
            meta={"id": domain_obj.id},  # type: ignore[call-arg]
            query=domain_obj.query,
            robot_id=domain_obj.robot_id,
        )

    def to_domain(self) -> RobotAutomation:
        """Create a domain model from this persistence model."""
        return RobotAutomation(
            id=self.meta.id, robot_id=self.robot_id, query=self.query
        )

    @classmethod
    def percolatable_document_from_domain(
        cls,
        percolatable: ReferenceWithChangeset,
    ) -> Self:
        """
        Create a percolatable document from a domain model.

        :param percolatable: The percolatable document to convert.
        :type percolatable: ReferenceWithChangeset
        :return: The persistence model.
        :rtype: RobotAutomationPercolationDocument
        """
        return cls(
            query=None,
            robot_id=None,
            reference=ReferenceDomainMixin.from_domain(percolatable),
            changeset=ReferenceDomainMixin.from_domain(percolatable.changeset),
        )
