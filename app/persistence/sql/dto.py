"""Data transfer objects used to interface between domain and sql models."""

from abc import ABC, abstractmethod
from typing import Generic, Self

from pydantic import Field

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

    preloaded: list[str] = Field(
        description="""
A list of attributes that have been preloaded from the SQL layer and can
hence be parsed into the domain layer.""",
        default_factory=list,
    )

    @classmethod
    @abstractmethod
    async def from_sql(
        cls, sql_obj: GenericSQLModelType, preloaded: list[str] | None = None
    ) -> Self:
        """Create a DTO from a sql model."""

    @abstractmethod
    async def to_sql(self) -> GenericSQLModelType:
        """Create a sql model from this DTO."""
