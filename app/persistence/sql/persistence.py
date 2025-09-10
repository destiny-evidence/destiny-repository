"""Objects used to interface with SQL implementations."""

import datetime
import uuid
from abc import abstractmethod
from enum import StrEnum, auto
from typing import Generic, Self

from pydantic import BaseModel, Field
from sqlalchemy import UUID, DateTime
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.persistence.generics import GenericDomainModelType
from app.utils.time_and_date import utc_now


class Base(DeclarativeBase, AsyncAttrs):
    """Base class for all SQLAlchemy models."""


# NB does not inherit ABC due to metadata mixing issues.
# https://stackoverflow.com/a/49668970
class GenericSQLPersistence(
    Base,
    Generic[GenericDomainModelType],
):
    """
    Generic implementation for a persistence model.

    At a minimum, the `from_domain` and `to_domain` methods should be implemented.
    """

    __abstract__ = True
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    @classmethod
    @abstractmethod
    def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a persistence model from a domain model."""

    @abstractmethod
    def to_domain(self, preload: list[str] | None = None) -> GenericDomainModelType:
        """Create a domain model from this persistence model."""


class RelationshipLoadType(StrEnum):
    """Supported types of loading relationships."""

    JOINED = auto()
    SELECTIN = auto()


class RelationshipInfo(BaseModel):
    """Optional custom information to store on SQL relationships."""

    max_recursion_depth: int | None = Field(
        default=None,
        description="Number of times to join a self-referential relationship.",
    )
    load_type: RelationshipLoadType = RelationshipLoadType.JOINED
    back_populates: str | None = Field(
        default=None,
        description="Back-populating relationships names. Used to avoid infinite "
        "recursion when propagating preloads.",
    )
