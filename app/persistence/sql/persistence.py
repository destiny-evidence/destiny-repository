"""Data transfer objects used to interface between domain and sql models."""

import uuid
from abc import abstractmethod
from typing import Generic, Self

from sqlalchemy import UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)

from app.persistence.generics import GenericDomainModelType


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

    @classmethod
    @abstractmethod
    async def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a persistence model from a domain model."""

    @abstractmethod
    async def to_domain(
        self, preload: list[str] | None = None
    ) -> GenericDomainModelType:
        """Create a domain model from this persistence model."""
