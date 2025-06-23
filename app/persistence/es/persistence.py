"""Objects used to interface with SQL implementations."""

from abc import abstractmethod
from typing import Generic, Self

from elasticsearch.dsl import AsyncDocument

from app.persistence.generics import GenericDomainModelType

INDEX_PREFIX = "destiny-repository"


# NB does not inherit ABC due to metadata mixing issues.
# https://stackoverflow.com/a/49668970
class GenericESPersistence(
    AsyncDocument,
    Generic[GenericDomainModelType],
):
    """
    Generic implementation for an elasticsearch persistence model.

    At a minimum, the `from_domain` and `to_domain` methods should be implemented.
    """

    __abstract__ = True

    @classmethod
    @abstractmethod
    async def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a persistence model from a domain model."""

    @abstractmethod
    async def to_domain(self) -> GenericDomainModelType:
        """Create a domain model from this persistence model."""

    class Index:
        """
        Index metadata for the persistence model.

        Implementer must define this subclass.
        """

        name: str
