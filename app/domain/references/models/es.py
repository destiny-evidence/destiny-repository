"""Objects used to interface with Elasticsearch implementations."""

import asyncio
from typing import Self

from elasticsearch.dsl import InnerDoc, Keyword, Nested, Object, Text, mapped_field
from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    EnhancementType,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    Visibility,
)
from app.persistence.es.persistence import GenericESPersistence


class ExternalIdentifierDocument(InnerDoc):
    """Persistence model for external identifiers in Elasticsearch."""

    identifier: str = mapped_field(Text(required=True))
    identifier_type: ExternalIdentifierType = mapped_field(
        Keyword(required=True, index=True)
    )
    other_identifier_name: str | None = mapped_field(Keyword())

    @classmethod
    async def from_domain(cls, domain_obj: LinkedExternalIdentifier) -> Self:
        """Create a persistence model from a domain ExternalIdentifier object."""
        return cls(
            identifier_type=domain_obj.identifier.identifier_type,
            identifier=str(domain_obj.identifier.identifier),
            other_identifier_name=getattr(
                domain_obj.identifier, "other_identifier_name", None
            ),
        )

    async def to_domain(self, reference_id: UUID4) -> LinkedExternalIdentifier:
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

    scheme: str | None = mapped_field(Keyword())
    label: str | None = mapped_field(Keyword())


class EnhancementContentDocument(InnerDoc):
    """
    Persistence model for enhancement content in Elasticsearch.

    We define anything we want to explicitly index here and map as dynamic in the
    parent document.
    """

    enhancement_type: EnhancementType = mapped_field(Keyword(required=True, index=True))
    annotations: list[AnnotationDocument] | None = mapped_field(
        Nested(AnnotationDocument, dynamic=True, required=False)
    )


class EnhancementDocument(InnerDoc):
    """Persistence model for enhancements in Elasticsearch."""

    visibility: Visibility = mapped_field(Keyword(required=True))
    source: str = mapped_field(Keyword(required=True))
    robot_version: str | None = mapped_field(Keyword())
    content: EnhancementContentDocument = mapped_field(
        Object(EnhancementContentDocument, dynamic=True, required=True)
    )

    @classmethod
    async def from_domain(cls, domain_obj: Enhancement) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            visibility=domain_obj.visibility,
            source=domain_obj.source,
            robot_version=domain_obj.robot_version,
            content=EnhancementContentDocument(**domain_obj.content.model_dump()),
        )

    async def to_domain(self, reference_id: UUID4) -> Enhancement:
        """Create a domain model from this persistence model."""
        return Enhancement(
            reference_id=reference_id,
            visibility=self.visibility,
            source=self.source,
            enhancement_type=self.content.enhancement_type,
            robot_version=self.robot_version,
            content=self.content.to_dict(),
        )


class ReferenceDocument(GenericESPersistence[Reference]):
    """Persistence model for references in Elasticsearch."""

    # mypy exceptions: https://stackoverflow.com/questions/51575931/class-inheritance-in-python-3-7-dataclasses

    id: UUID4 = mapped_field(Keyword(required=True, index=True))  # type: ignore[misc]
    visibility: Visibility = mapped_field(Keyword(required=True))  # type: ignore[misc]
    identifiers: list[ExternalIdentifierDocument] = mapped_field(  # type: ignore[misc]
        Nested(ExternalIdentifierDocument)
    )
    enhancements: list[EnhancementDocument] = mapped_field(Nested(EnhancementDocument))  # type: ignore[misc]

    @classmethod
    async def from_domain(cls, domain_obj: Reference) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            id=domain_obj.id,
            visibility=domain_obj.visibility,
            identifiers=await asyncio.gather(
                *(
                    ExternalIdentifierDocument.from_domain(identifier)
                    for identifier in domain_obj.identifiers or []
                )
            ),
            enhancements=await asyncio.gather(
                *(
                    EnhancementDocument.from_domain(enhancement)
                    for enhancement in domain_obj.enhancements or []
                )
            ),
        )

    async def to_domain(self) -> Reference:
        """Create a domain model from this persistence model."""
        return Reference(
            id=self.id,
            visibility=self.visibility,
            identifiers=await asyncio.gather(
                *(
                    identifier.to_domain(reference_id=self.id)
                    for identifier in self.identifiers
                )
            ),
            enhancements=await asyncio.gather(
                *(
                    enhancement.to_domain(reference_id=self.id)
                    for enhancement in self.enhancements
                )
            ),
        )
