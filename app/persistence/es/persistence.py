"""Objects used to interface with SQL implementations."""

from abc import abstractmethod
from typing import Generic, Self

from pydantic import BaseModel

from app.persistence.generics import GenericDomainModelType


# NB does not inherit ABC due to metadata mixing issues.
# https://stackoverflow.com/a/49668970
class GenericESPersistence(
    Generic[GenericDomainModelType],
    BaseModel,
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
