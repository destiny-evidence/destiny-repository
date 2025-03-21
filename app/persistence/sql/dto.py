"""Data transfer objects used to interface between domain and sql models."""

from abc import ABC, abstractmethod
from typing import Generic, Self

from app.persistence.dto import GenericDomainModelType, GenericDTO
from app.persistence.sql.generics import GenericSQLModelType


class GenericSQLDTO(
    GenericDTO[GenericDomainModelType],
    Generic[GenericDomainModelType, GenericSQLModelType],
    ABC,
):
    """
    Generic Data Transfer Object for a domain model.

    At a minimum, the `from_sql` and `to_sql` methods should be implemented.
    """

    @classmethod
    @abstractmethod
    async def from_sql(cls, sql_obj: GenericSQLModelType) -> Self:
        """Create a DTO from a sql model."""

    @abstractmethod
    async def to_sql(self) -> GenericSQLModelType:
        """Create a sql model from this DTO."""
