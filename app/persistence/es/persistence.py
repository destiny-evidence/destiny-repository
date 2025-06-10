"""Objects used to interface with SQL implementations."""

import datetime
from abc import abstractmethod
from typing import Any, Generic, Self

from elasticsearch.dsl import AsyncDocument, Date, mapped_field

from app.persistence.generics import GenericDomainModelType
from app.utils.time_and_date import utc_now


# NB does not inherit ABC due to metadata mixing issues.
# https://stackoverflow.com/a/49668970
class GenericESPersistence(
    Generic[GenericDomainModelType],
    AsyncDocument,
):
    """
    Generic implementation for an elasticsearch persistence model.

    At a minimum, the `from_domain` and `to_domain` methods should be implemented.
    """

    __abstract__ = True

    created_at: datetime.datetime = mapped_field(Date(), default_factory=utc_now)
    updated_at: datetime.datetime = mapped_field(Date(), default_factory=utc_now)

    @classmethod
    @abstractmethod
    async def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a persistence model from a domain model."""

    @abstractmethod
    async def to_domain(self) -> GenericDomainModelType:
        """Create a domain model from this persistence model."""

    class Index:
        """Index metadata for the persistence model."""

        name: str = "auto_set_by_subclass"

    def __init_subclass__(cls, **kwargs: dict[str, Any]) -> None:
        """Set the index name to the lowercase class name when a subclass is created."""
        super().__init_subclass__(**kwargs)
        cls.Index.name = cls.__name__.lower()
