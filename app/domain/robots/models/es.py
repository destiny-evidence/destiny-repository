"""Objects used to interface with Elasticsearch implementations."""

import asyncio
import uuid
from typing import Any, Self

from elasticsearch.dsl import (
    InnerDoc,
    Keyword,
    Object,
    Percolator,
    mapped_field,
)

from app.domain.references.models.es import (
    EnhancementDocument,
    ExternalIdentifierDocument,
    ReferenceDocumentFields,
)
from app.domain.references.models.models import Enhancement, Reference
from app.domain.robots.models.models import RobotAutomation
from app.persistence.es.persistence import GenericESPersistence, Percolatable


class _ReferenceDocument(InnerDoc, ReferenceDocumentFields):
    """
    Redefinition of ReferenceDocument as an InnerDoc.

    (It's a top-level document in the main data index).
    """

    @classmethod
    async def from_domain(cls, domain_obj: Reference) -> Self:
        return cls(
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


class _RobotAutomationPercolationFields:
    """Fields that the robot automation percolator queries against in Elasticsearch."""

    reference: _ReferenceDocument | None = mapped_field(
        Object(_ReferenceDocument, required=False, index=False),
    )
    enhancement: EnhancementDocument | None = mapped_field(
        Object(EnhancementDocument, required=False, index=False),
    )
    # The ID of the reference that this query is percolating against.
    # This is used to link the percolation result back to the reference.
    reference_id: uuid.UUID | None = mapped_field(
        Keyword(required=False, index=False),
    )


class RobotAutomationPercolatable(_RobotAutomationPercolationFields, Percolatable):
    """Percolatable document for robot automation in Elasticsearch."""

    @classmethod
    async def from_domain(
        cls, domain_obj: Reference | Enhancement, reference_id: uuid.UUID
    ) -> Self:
        """Create a domain model from this percolatable document."""
        return cls(
            reference=await _ReferenceDocument.from_domain(domain_obj)
            if isinstance(domain_obj, Reference)
            else None,
            enhancement=await EnhancementDocument.from_domain(domain_obj)
            if isinstance(domain_obj, Enhancement)
            else None,
            reference_id=reference_id,
        )


class RobotAutomationPercolationDocument(
    GenericESPersistence[RobotAutomation], _RobotAutomationPercolationFields
):
    """Persistence model for robot automation percolation in Elasticsearch."""

    query: dict[str, Any] = mapped_field(
        Percolator(required=True),
    )
    robot_id: uuid.UUID = mapped_field(
        Keyword(required=True),
    )

    @classmethod
    async def from_domain(cls, domain_obj: RobotAutomation) -> Self:
        """Create a persistence model from a domain model."""
        return cls(
            # Parent's parent does accept meta, but mypy doesn't like it here.
            # Ignoring easier than chaining __init__ methods IMO.
            meta={"id": domain_obj.id},  # type: ignore[call-arg]
            query=domain_obj.query,
            robot_id=domain_obj.robot_id,
        )

    async def to_domain(self) -> RobotAutomation:
        """Create a domain model from this persistence model."""
        return RobotAutomation(
            id=self.meta.id, robot_id=self.robot_id, query=self.query
        )

    class Index:
        """Index metadata for the persistence model."""

        name = "robot_automation_percolation"
