"""
Objects used to interface with persistence implementations.

These are used only by repositories, which are the only objects that should be aware
of persistence.
"""

from abc import ABC, abstractmethod
from typing import Generic, Self

from app.persistence.generics import GenericDomainModelType


class GenericPersistence(Generic[GenericDomainModelType], ABC):
    """
    Generic implementation for a persistence model.

    At a minimum, the `from_domain` and `to_domain` methods should be implemented.

    This is not inherited anywhere as the mixing of metaclasses causes mayhem (for
    instance, ABCMeta and SQLAlchemy's DeclarativeMeta) but is used as a guide to define
    the interface new persistence implementations should follow.
    https://stackoverflow.com/a/49668970
    """

    @classmethod
    @abstractmethod
    async def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """
        Create a persistence model from a domain model.

        :param domain_obj: Domain model instance to be converted.

        :return: Persistence model instance.
        """

    @abstractmethod
    async def to_domain(self) -> GenericDomainModelType:
        """
        Create a domain model from this persistence model.

        :return: Domain model instance.
        """
