"""Objects used to interface with SQL implementations."""

import asyncio
import uuid
from typing import Any, Self

from sqlalchemy import UUID, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.references.models.models import (
    BatchEnhancementRequest as DomainBatchEnhancementRequest,
)
from app.domain.references.models.models import (
    BatchEnhancementRequestStatus,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    Visibility,
)
from app.domain.references.models.models import (
    Enhancement as DomainEnhancement,
)
from app.domain.references.models.models import (
    EnhancementRequest as DomainEnhancementRequest,
)
from app.domain.references.models.models import (
    LinkedExternalIdentifier as DomainExternalIdentifier,
)
from app.domain.references.models.models import (
    Reference as DomainReference,
)
from app.domain.references.models.models import (
    RobotAutomation as DomainRobotAutomation,
)
from app.persistence.blob.models import BlobStorageFile
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
        "ExternalIdentifier",
        back_populates="reference",
        cascade="all, delete, delete-orphan",
    )
    enhancements: Mapped[list["Enhancement"]] = relationship(
        "Enhancement", back_populates="reference", cascade="all, delete, delete-orphan"
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainReference) -> Self:
        """Create a persistence model from a domain Reference object."""
        return cls(
            id=domain_obj.id,
            visibility=domain_obj.visibility,
            identifiers=await asyncio.gather(
                *(
                    ExternalIdentifier.from_domain(identifier)
                    for identifier in domain_obj.identifiers or []
                )
            ),
            enhancements=await asyncio.gather(
                *(
                    Enhancement.from_domain(enhancement)
                    for enhancement in domain_obj.enhancements or []
                )
            ),
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
        Index("ix_external_identifier_reference_id", "reference_id"),
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainExternalIdentifier) -> Self:
        """Create a persistence model from a domain ExternalIdentifier object."""
        return cls(
            id=domain_obj.id,
            reference_id=domain_obj.reference_id,
            identifier_type=domain_obj.identifier.identifier_type,
            identifier=str(domain_obj.identifier.identifier),
            other_identifier_name=domain_obj.identifier.other_identifier_name  # type: ignore[union-attr]
            if hasattr(domain_obj.identifier, "other_identifier_name")
            else None,
        )

    async def to_domain(
        self, preload: list[str] | None = None
    ) -> DomainExternalIdentifier:
        """Convert the persistence model into a Domain ExternalIdentifier object."""
        return DomainExternalIdentifier(
            id=self.id,
            reference_id=self.reference_id,
            identifier=ExternalIdentifierAdapter.validate_python(
                {
                    "identifier": self.identifier,
                    "identifier_type": self.identifier_type,
                    "other_identifier_name": self.other_identifier_name,
                }
            ),
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
    robot_version: Mapped[str] = mapped_column(String, nullable=True)
    derived_from: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID), nullable=True
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    reference: Mapped["Reference"] = relationship(
        "Reference", back_populates="enhancements"
    )

    __table_args__ = (Index("ix_enhancement_reference_id", "reference_id"),)

    @classmethod
    async def from_domain(cls, domain_obj: DomainEnhancement) -> Self:
        """Create a persistence model from a domain Enhancement object."""
        return cls(
            id=domain_obj.id,
            reference_id=domain_obj.reference_id,
            enhancement_type=domain_obj.content.enhancement_type,
            source=domain_obj.source,
            visibility=domain_obj.visibility,
            robot_version=domain_obj.robot_version,
            derived_from=domain_obj.derived_from,
            content=domain_obj.content.model_dump(mode="json"),
        )

    async def to_domain(self, preload: list[str] | None = None) -> DomainEnhancement:
        """Convert the persistence model into a Domain Enhancement object."""
        return DomainEnhancement(
            id=self.id,
            source=self.source,
            visibility=self.visibility,
            reference_id=self.reference_id,
            robot_version=self.robot_version,
            derived_from=self.derived_from,
            content=self.content,
            reference=await self.reference.to_domain()
            if "reference" in (preload or [])
            else None,
        )


class EnhancementRequest(GenericSQLPersistence[DomainEnhancementRequest]):
    """
    SQL Persistence model for an EnhancementRequest.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "enhancement_request"

    reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("reference.id"), nullable=False
    )

    robot_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)

    request_status: Mapped[EnhancementRequestStatus] = mapped_column(
        ENUM(
            *[status.value for status in EnhancementRequestStatus],
            name="request_status",
        )
    )

    source: Mapped[str | None] = mapped_column(String, nullable=True)

    enhancement_parameters: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    error: Mapped[str | None] = mapped_column(String, nullable=True)

    reference: Mapped["Reference"] = relationship("Reference")

    @classmethod
    async def from_domain(cls, domain_obj: DomainEnhancementRequest) -> Self:
        """Create a persistence model from a domain Enhancement object."""
        return cls(
            id=domain_obj.id,
            reference_id=domain_obj.reference_id,
            robot_id=domain_obj.robot_id,
            request_status=domain_obj.request_status,
            source=domain_obj.source,
            enhancement_parameters=domain_obj.enhancement_parameters
            if domain_obj.enhancement_parameters
            else None,
            error=domain_obj.error,
        )

    async def to_domain(
        self, preload: list[str] | None = None
    ) -> DomainEnhancementRequest:
        """Convert the persistence model into a Domain Enhancement object."""
        return DomainEnhancementRequest(
            id=self.id,
            reference_id=self.reference_id,
            robot_id=self.robot_id,
            request_status=self.request_status,
            source=self.source,
            enhancement_parameters=self.enhancement_parameters
            if self.enhancement_parameters
            else {},
            error=self.error,
            reference=await self.reference.to_domain()
            if "reference" in (preload or [])
            else None,
        )


class BatchEnhancementRequest(GenericSQLPersistence[DomainBatchEnhancementRequest]):
    """
    SQL Persistence model for a BatchEnhancementRequest.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "batch_enhancement_request"

    reference_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID), nullable=False)

    robot_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)

    request_status: Mapped[BatchEnhancementRequestStatus] = mapped_column(
        ENUM(
            *[status.value for status in BatchEnhancementRequestStatus],
            name="batch_enhancement_request_status",
        )
    )

    source: Mapped[str | None] = mapped_column(String, nullable=True)

    enhancement_parameters: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    reference_data_file: Mapped[str | None] = mapped_column(String, nullable=True)
    result_file: Mapped[str | None] = mapped_column(String, nullable=True)
    validation_result_file: Mapped[str | None] = mapped_column(String, nullable=True)

    error: Mapped[str | None] = mapped_column(String, nullable=True)

    @classmethod
    async def from_domain(cls, domain_obj: DomainBatchEnhancementRequest) -> Self:
        """Create a persistence model from a domain Enhancement object."""
        return cls(
            id=domain_obj.id,
            reference_ids=domain_obj.reference_ids,
            robot_id=domain_obj.robot_id,
            request_status=domain_obj.request_status,
            source=domain_obj.source,
            enhancement_parameters=domain_obj.enhancement_parameters
            if domain_obj.enhancement_parameters
            else None,
            error=domain_obj.error,
            reference_data_file=await domain_obj.reference_data_file.to_sql()
            if domain_obj.reference_data_file
            else None,
            result_file=await domain_obj.result_file.to_sql()
            if domain_obj.result_file
            else None,
            validation_result_file=await domain_obj.validation_result_file.to_sql()
            if domain_obj.validation_result_file
            else None,
        )

    async def to_domain(
        self,
        preload: list[str] | None = None,  # noqa: ARG002
    ) -> DomainBatchEnhancementRequest:
        """Convert the persistence model into a Domain Enhancement object."""
        return DomainBatchEnhancementRequest(
            id=self.id,
            reference_ids=self.reference_ids,
            robot_id=self.robot_id,
            request_status=self.request_status,
            source=self.source,
            enhancement_parameters=self.enhancement_parameters
            if self.enhancement_parameters
            else {},
            error=self.error,
            reference_data_file=await BlobStorageFile.from_sql(self.reference_data_file)
            if self.reference_data_file
            else None,
            result_file=await BlobStorageFile.from_sql(self.result_file)
            if self.result_file
            else None,
            validation_result_file=await BlobStorageFile.from_sql(
                self.validation_result_file
            )
            if self.validation_result_file
            else None,
        )


class RobotAutomation(GenericSQLPersistence[DomainRobotAutomation]):
    """
    SQL Persistence model for a Robot Automation.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "robot_automation"

    robot_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("robot.id"), nullable=False
    )

    query: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "robot_id",
            "query",
            name="uix_robot_automation",
        ),
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainRobotAutomation) -> Self:
        """Create a persistence model from a domain RobotAutomation object."""
        return cls(
            id=domain_obj.id,
            robot_id=domain_obj.robot_id,
            query=domain_obj.query,
        )

    async def to_domain(
        self,
        preload: list[str] | None = None,  # noqa: ARG002
    ) -> DomainRobotAutomation:
        """Convert the persistence model into a Domain RobotAutomation object."""
        return DomainRobotAutomation(
            id=self.id,
            robot_id=self.robot_id,
            query=self.query,
        )
