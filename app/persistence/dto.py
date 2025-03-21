"""Data transfer objects used to interface between domain and persistence models."""

from abc import ABC, abstractmethod
from typing import Generic, Self

from pydantic import BaseModel

from app.persistence.generics import GenericDomainModelType


class GenericDTO(ABC, Generic[GenericDomainModelType], BaseModel):
    """
    Generic Data Transfer Object for a domain model.

    This should be implemented by each persistence implementation.
    """

    @abstractmethod
    @classmethod
    async def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a DTO from a domain model."""

    @abstractmethod
    async def to_domain(self) -> GenericDomainModelType:
        """Create a domain model from this DTO."""
