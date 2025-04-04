"""Objects used to interface with SQL implementations."""

import asyncio
import json
import uuid
from typing import Self

from sqlalchemy import UUID, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.references.models.models import (
    Enhancement as DomainEnhancement,
)
from app.domain.references.models.models import (
    EnhancementType,
    ExternalIdentifierType,
    Visibility,
)
from app.domain.references.models.models import (
    ExternalIdentifier as DomainExternalIdentifier,
)
from app.domain.references.models.models import (
    Reference as DomainReference,
)
from app.persistence.sql.persistence import GenericSQLPersistence


class Reference(GenericSQLPersistence[DomainReference]):
    """
    SQL Persistence model for a Reference.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "reference"

    visibility: Mapped[Visibility] = mapped_column(
        ENUM(
            *[status.value for status in Visibility],
            name="visibility",
        ),
        nullable=False,
    )

    identifiers: Mapped[list["ExternalIdentifier"]] = relationship(
        "ExternalIdentifier", back_populates="reference"
    )
    enhancements: Mapped[list["Enhancement"]] = relationship(
        "Enhancement", back_populates="reference"
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainReference) -> Self:
        """Create a persistence model from a domain Reference object."""
        return cls(
            id=domain_obj.id,
            visibility=domain_obj.visibility,
        )

    async def to_domain(self, preload: list[str] | None = None) -> DomainReference:
        """Convert the persistence model into a Domain Reference object."""
        return DomainReference(
            id=self.id,
            visibility=self.visibility,
            identifiers=await asyncio.gather(
                *(identifier.to_domain() for identifier in self.identifiers)
            )
            if "identifiers" in (preload or [])
            else None,
            enhancements=await asyncio.gather(
                *(enhancement.to_domain() for enhancement in self.enhancements)
            )
            if "enhancements" in (preload or [])
            else None,
        )


class ExternalIdentifier(GenericSQLPersistence[DomainExternalIdentifier]):
    """
    SQL Persistence model for an ExternalIdentifier.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "external_identifier"

    reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("reference.id"), nullable=False
    )
    identifier_type: Mapped[ExternalIdentifierType] = mapped_column(
        ENUM(
            *[identifier.value for identifier in ExternalIdentifierType],
            name="external_identifier_type",
        ),
        nullable=False,
    )
    other_identifier_name: Mapped[str] = mapped_column(
        String, nullable=True, default=None
    )
    identifier: Mapped[str] = mapped_column(String, nullable=False)

    reference: Mapped["Reference"] = relationship(
        "Reference", back_populates="identifiers"
    )

    __table_args__ = (
        UniqueConstraint(
            "identifier_type",
            "identifier",
            "other_identifier_name",
            name="uix_external_identifier",
            postgresql_nulls_not_distinct=True,
        ),
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainExternalIdentifier) -> Self:
        """Create a persistence model from a domain ExternalIdentifier object."""
        return cls(
            id=domain_obj.id,
            reference_id=domain_obj.reference_id,
            identifier_type=domain_obj.identifier_type,
            identifier=str(domain_obj.identifier),
            other_identifier_name=domain_obj.other_identifier_name,
        )

    async def to_domain(
        self, preload: list[str] | None = None
    ) -> DomainExternalIdentifier:
        """Convert the persistence model into a Domain ExternalIdentifier object."""
        return DomainExternalIdentifier(
            id=self.id,
            reference_id=self.reference_id,
            identifier_type=self.identifier_type,
            identifier=self.identifier,
            other_identifier_name=self.other_identifier_name,
            reference=await self.reference.to_domain()
            if "reference" in (preload or [])
            else None,
        )


class Enhancement(GenericSQLPersistence[DomainEnhancement]):
    """
    SQL Persistence model for an Enhancement.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "enhancement"

    visibility: Mapped[Visibility] = mapped_column(
        ENUM(
            *[status.value for status in Visibility],
            name="visibility",
        ),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("reference.id"), nullable=False
    )
    enhancement_type: Mapped[EnhancementType] = mapped_column(
        ENUM(
            *[enhancement.value for enhancement in EnhancementType],
            name="enhancement_type",
        ),
        nullable=False,
    )
    processor_version: Mapped[str] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(JSONB, nullable=False)
    content_version: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)

    reference: Mapped["Reference"] = relationship(
        "Reference", back_populates="enhancements"
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainEnhancement) -> Self:
        """Create a persistence model from a domain Enhancement object."""
        return cls(
            id=domain_obj.id,
            reference_id=domain_obj.reference_id,
            enhancement_type=domain_obj.enhancement_type,
            source=domain_obj.source,
            visibility=domain_obj.visibility,
            processor_version=domain_obj.processor_version,
            content_version=domain_obj.content_version,
            content=domain_obj.content.model_dump_json(),
        )

    async def to_domain(self, preload: list[str] | None = None) -> DomainEnhancement:
        """Convert the persistence model into a Domain Enhancement object."""
        return DomainEnhancement(
            id=self.id,
            source=self.source,
            visibility=self.visibility,
            reference_id=self.reference_id,
            enhancement_type=self.enhancement_type,
            processor_version=self.processor_version,
            content=json.loads(self.content),
            content_version=self.content_version,
            reference=await self.reference.to_domain()
            if "reference" in (preload or [])
            else None,
        )
