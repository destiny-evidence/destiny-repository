"""Objects used to interface with Elasticsearch implementations."""

import uuid
from typing import Any, Self
from unicodedata import normalize

import destiny_sdk
from elasticsearch.dsl import (
    Boolean,
    InnerDoc,
    Keyword,
    Nested,
    Object,
    Percolator,
    Text,
    mapped_field,
)
from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    EnhancementType,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    RobotAutomation,
    Visibility,
)
from app.persistence.es.persistence import (
    INDEX_PREFIX,
    GenericESPersistence,
)


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


class ReferenceMixin(InnerDoc):
    """1:1 mapping of Reference domain model to Elasticsearch document."""

    visibility: Visibility = mapped_field(Keyword(required=True))
    identifiers: list[ExternalIdentifierDocument] = mapped_field(
        Nested(ExternalIdentifierDocument)
    )
    enhancements: list[EnhancementDocument] = mapped_field(Nested(EnhancementDocument))

    @classmethod
    def reference_mixin_from_domain(cls, reference: Reference) -> dict[str, Any]:
        """Create the kwargs for an ES model relevant to ReferenceMixin."""
        return {
            "visibility": reference.visibility,
            "identifiers": [
                ExternalIdentifierDocument.from_domain(identifier)
                for identifier in reference.identifiers or []
            ],
            "enhancements": [
                EnhancementDocument.from_domain(enhancement)
                for enhancement in reference.enhancements or []
            ],
        }

    def reference_mixin_to_domain(self, reference_id: str) -> dict[str, Any]:
        """Create the kwargs for a domain model relevant to ReferenceMixin."""
        return {
            "visibility": self.visibility,
            "identifiers": [
                identifier.to_domain(reference_id=uuid.UUID(reference_id))
                for identifier in self.identifiers
            ],
            "enhancements": [
                enhancement.to_domain(reference_id=uuid.UUID(reference_id))
                for enhancement in self.enhancements
            ],
        }


class ReferenceDeduplicationMixin(InnerDoc):
    """Mixin to project Reference fields relevant to deduplication."""

    title: str | None = mapped_field(Text(required=False), default=None)
    authors: list[str] | None = mapped_field(
        Text(required=False),
        default=None,
    )
    publication_year: int | None = mapped_field(
        Keyword(required=False),
        default=None,
    )

    @classmethod
    def reference_deduplication_mixin_from_domain(
        cls, reference: Reference
    ) -> dict[str, Any]:
        """Create the kwargs for an ES model relevant to ReferenceDeduplicationMixin."""
        if not reference.enhancements:
            return {}

        title, authorship, publication_year = None, None, None
        for enhancement in reference.enhancements:
            # NB at present we have no way of discriminating between multiple
            # bibliographic enhancements, nor are they ordered. This takes a
            # random one (but hydrates in the case of one bibliographic enhancement
            # missing a field while the other has it present).
            if enhancement.content.enhancement_type == EnhancementType.BIBLIOGRAPHIC:
                # Hydrate if exists on enhancement, otherwise use prior value
                title = enhancement.content.title or title
                authorship = enhancement.content.authorship or authorship
                publication_year = (
                    enhancement.content.publication_year
                    or (
                        enhancement.content.publication_date.year
                        if enhancement.content.publication_date
                        else None
                    )
                    or publication_year
                )

        # Title normalization: strip whitespace and title case
        if title:
            title = normalize("NFC", title.strip()).title()

        # Author normalization:
        # Maintain first and last author, sort middle authors by name
        # Then strip whitespace and title case
        authors = None
        if authorship:
            authorship = sorted(
                authorship,
                key=lambda author: (
                    {
                        destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
                        destiny_sdk.enhancements.AuthorPosition.LAST: 1,
                    }.get(author.position, 0),
                    author.display_name,
                ),
            )
            authors = [
                normalize("NFC", author.display_name.strip()).title()
                for author in authorship
            ]

        return {
            "title": title,
            "authors": authors,
            "publication_year": publication_year,
        }


class ReferenceDocument(
    GenericESPersistence[Reference], ReferenceMixin, ReferenceDeduplicationMixin
):
    """Persistence model for references in Elasticsearch."""

    class Index:
        """Index metadata for the persistence model."""

        name = f"{INDEX_PREFIX}-reference"

    @classmethod
    def from_domain(cls, domain_obj: Reference) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            # Parent's parent does accept meta, but mypy doesn't like it here.
            # Ignoring easier than chaining __init__ methods IMO.
            meta={"id": domain_obj.id},  # type: ignore[call-arg]
            **cls.reference_mixin_from_domain(domain_obj),
            **cls.reference_deduplication_mixin_from_domain(domain_obj),
        )

    def to_domain(self) -> Reference:
        """Create a domain model from this persistence model."""
        return Reference(
            id=self.meta.id,
            **self.reference_mixin_to_domain(self.meta.id),
        )


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

        name = f"{INDEX_PREFIX}-robot-automation-percolation"

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
            reference=ReferenceInnerDocument.from_domain(percolatable)
            if isinstance(percolatable, Reference)
            else None,
            enhancement=EnhancementDocument.from_domain(percolatable)
            if isinstance(percolatable, Enhancement)
            else None,
        )
