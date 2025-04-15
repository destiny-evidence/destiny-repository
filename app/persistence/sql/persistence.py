"""Objects used to interface with SQL implementations."""

import datetime
import uuid
from abc import abstractmethod
from typing import Generic, Self

from sqlalchemy import UUID, DateTime
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)

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
    Generic implementation for a SQLAlchemy persistence model.

    All SQLAlchemy persistence models should inherit from this class. The
    DeclarativeBase has been mixed in to allow for the use of SQLAlchemy's ORM features.

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
    async def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """
        Create a persistence model from a domain model.

        :param domain_obj: Domain model instance to be converted.

        :return: Persistence model instance.
        """

    @abstractmethod
    async def to_domain(
        self, preload: list[str] | None = None
    ) -> GenericDomainModelType:
        """
        Create a domain model from this persistence model.

        :param preload: A list of attributes that have already been preloaded into this
                        persistence instance.

        :return: Domain model instance.
        """
