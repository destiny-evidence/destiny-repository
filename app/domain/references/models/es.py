"""Objects used to interface with Elasticsearch implementations."""

from typing import Self

from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    ExternalIdentifier,
    Visibility,
)
from app.domain.references.models.models import (
    Reference as DomainReference,
)
from app.persistence.es.persistence import GenericESPersistence


class Reference(GenericESPersistence[DomainReference]):
    """Persistence model for references in Elasticsearch."""

    id: UUID4
    visibility: Visibility
    identifiers: list[ExternalIdentifier]
    enhancements: list[Enhancement]

    @classmethod
    async def from_domain(cls, domain_obj: DomainReference) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            id=domain_obj.id,
            visibility=domain_obj.visibility,
            identifiers=domain_obj.identifiers,
            enhancements=domain_obj.enhancements,
        )

    async def to_domain(self) -> DomainReference:
        """Create a domain model from this persistence model."""
        return DomainReference(
            id=self.id,
            visibility=self.visibility,
            identifiers=self.identifiers,
            enhancements=self.enhancements,
        )
