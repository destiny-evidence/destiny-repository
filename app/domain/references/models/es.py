"""Objects used to interface with Elasticsearch implementations."""

import uuid
from typing import Any, Self

from elasticsearch.dsl import (
    Boolean,
    InnerDoc,
    Integer,
    Keyword,
    Nested,
    Object,
    Percolator,
    Text,
    mapped_field,
)
from pydantic import UUID4

from app.core.config import get_settings
from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
    Enhancement,
    EnhancementType,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    RobotAutomation,
    Visibility,
)
from app.domain.references.models.projections import (
    CandidateCanonicalSearchFieldsProjection,
)
from app.persistence.es.persistence import (
    GenericESPersistence,
)

settings = get_settings()


class ExternalIdentifierDocument(InnerDoc):
    """Persistence model for external identifiers in Elasticsearch."""

    identifier: str = mapped_field(Text(required=True))
    identifier_type: ExternalIdentifierType = mapped_field(Keyword(required=True))
    other_identifier_name: str | None = mapped_field(Keyword())

    @classmethod
    def from_domain(cls, domain_obj: LinkedExternalIdentifier) -> Self:
        """Create a persistence model from a domain ExternalIdentifier object."""
        return cls(
            identifier_type=domain_obj.identifier.identifier_type,
            identifier=str(domain_obj.identifier.identifier),
            other_identifier_name=getattr(
                domain_obj.identifier, "other_identifier_name", None
            ),
        )

    def to_domain(self, reference_id: UUID4) -> LinkedExternalIdentifier:
        """Convert the persistence model into a Domain ExternalIdentifier object."""
        return LinkedExternalIdentifier(
            reference_id=reference_id,
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

    id: UUID4 = mapped_field(Keyword(required=True, index=True))
    visibility: Visibility = mapped_field(Keyword(required=True))
    source: str = mapped_field(Keyword(required=True))
    robot_version: str | None = mapped_field(Keyword())
    content: EnhancementContentDocument = mapped_field(
        Object(EnhancementContentDocument, required=True)
    )

    @classmethod
    def from_domain(cls, domain_obj: Enhancement) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            id=domain_obj.id,
            visibility=domain_obj.visibility,
            source=domain_obj.source,
            robot_version=domain_obj.robot_version,
            content=EnhancementContentDocument(
                **domain_obj.content.model_dump(mode="json")
            ),
        )

    def to_domain(self, reference_id: UUID4) -> Enhancement:
        """Create a domain model from this persistence model."""
        return Enhancement(
            id=self.id,
            reference_id=reference_id,
            visibility=self.visibility,
            source=self.source,
            enhancement_type=self.content.enhancement_type,
            robot_version=self.robot_version,
            content=self.content.to_dict(),
        )


class ReferenceDomainMixin(InnerDoc):
    """1:1 mapping of Reference domain model to Elasticsearch document."""

    visibility: Visibility = mapped_field(Keyword(required=True))
    identifiers: list[ExternalIdentifierDocument] = mapped_field(
        Nested(ExternalIdentifierDocument)
    )
    enhancements: list[EnhancementDocument] = mapped_field(Nested(EnhancementDocument))

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
        )

    def to_domain(self) -> Reference:
        """Create a domain model from a ReferenceDomainMixin."""
        reference_id = uuid.UUID(self.meta.id)
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


class ReferenceCandidateCanonicalMixin(InnerDoc):
    """Mixin to project Reference fields relevant to deduplication."""

    if settings.feature_flags.deduplication:
        title: str | None = mapped_field(Text(required=False), default=None)
        authors: list[str] | None = mapped_field(
            Text(required=False),
            default=None,
        )
        publication_year: int | None = mapped_field(
            Integer(required=False),
            default=None,
        )

    @classmethod
    def from_projection(cls, projection: CandidateCanonicalSearchFields) -> Self:
        """Create a ReferenceCandidateCanonicalMixin from the search projection."""
        return cls(
            title=projection.title,
            authors=projection.authors,
            publication_year=projection.publication_year,
        )

    @classmethod
    def from_domain(cls, reference: Reference) -> Self:
        """Create the ES ReferenceDeduplicationMixin."""
        return cls.from_projection(
            CandidateCanonicalSearchFieldsProjection.get_from_reference(reference)
        )


class ReferenceDocument(
    GenericESPersistence[Reference],
    ReferenceDomainMixin,
    ReferenceCandidateCanonicalMixin,
):
    """Persistence model for references in Elasticsearch."""

    class Index:
        """Index metadata for the persistence model."""

        name = f"{settings.es_config.index_prefix}reference"

    @classmethod
    def from_domain(cls, domain_obj: Reference) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            # Parent's parent does accept meta, but mypy doesn't like it here.
            # Ignoring easier than chaining __init__ methods IMO.
            meta={"id": domain_obj.id},  # type: ignore[call-arg]
            **ReferenceDomainMixin.from_domain(domain_obj).to_dict(),
            **(
                ReferenceCandidateCanonicalMixin.from_domain(domain_obj).to_dict()
                if settings.feature_flags.deduplication
                else {}
            ),
        )

    def to_domain(self) -> Reference:
        """Create a domain model from this persistence model."""
        return ReferenceDomainMixin.to_domain(self)


class ReferenceInnerDocument(InnerDoc):
    """InnerDoc for references in Elasticsearch."""

    visibility: Visibility = mapped_field(Keyword(required=True))
    identifiers: list[ExternalIdentifierDocument] = mapped_field(
        Nested(ExternalIdentifierDocument)
    )
    enhancements: list[EnhancementDocument] = mapped_field(Nested(EnhancementDocument))

    @classmethod
    def from_domain(cls, domain_obj: Reference) -> Self:
        """Create a ReferenceInnerDocument from a domain Reference object."""
        return cls(
            visibility=domain_obj.visibility,
            identifiers=[
                ExternalIdentifierDocument.from_domain(identifier)
                for identifier in domain_obj.identifiers or []
            ],
            enhancements=[
                EnhancementDocument.from_domain(enhancement)
                for enhancement in domain_obj.enhancements or []
            ],
        )


class RobotAutomationPercolationDocument(GenericESPersistence[RobotAutomation]):
    """
    Persistence model for robot automation percolation in Elasticsearch.

    This model serves two purposes in order to fully define the index: a persistence
    layer for queries that dictate robot automation, and a percolator layer to convert
    domain models to queryable documents that run against said queries.
    """

    class Index:
        """Index metadata for the persistence model."""

        name = f"{settings.es_config.index_prefix}robot-automation-percolation"

    query: dict[str, Any] | None = mapped_field(
        Percolator(required=False),
    )
    robot_id: uuid.UUID | None = mapped_field(
        Keyword(required=False),
    )
    reference: ReferenceInnerDocument | None = mapped_field(
        Object(ReferenceInnerDocument, required=False),
    )
    enhancement: EnhancementDocument | None = mapped_field(
        Object(EnhancementDocument, required=False),
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
        percolatable: Reference | Enhancement,
    ) -> Self:
        """
        Create a percolatable document from a domain model.

        :param percolatable: The percolatable document to convert.
        :type percolatable: Reference | Enhancement
        :return: The persistence model.
        :rtype: RobotAutomationPercolationDocument
        """
        return cls(
            query=None,
            robot_id=None,
            reference=(
                ReferenceInnerDocument.from_domain(percolatable)
                if isinstance(percolatable, Reference)
                else None
            ),
            enhancement=(
                EnhancementDocument.from_domain(percolatable)
                if isinstance(percolatable, Enhancement)
                else None
            ),
        )
