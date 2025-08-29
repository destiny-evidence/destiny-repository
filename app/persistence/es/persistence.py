"""Objects used to interface with SQL implementations."""

import uuid
from abc import abstractmethod
from typing import Generic, Self

from elasticsearch.dsl import AsyncDocument
from pydantic import BaseModel

from app.core.config import get_settings
from app.persistence.generics import GenericDomainModelType

settings = get_settings()

INDEX_PREFIX = f"destiny-repository-{settings.env}"


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
    def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a persistence model from a domain model."""

    @abstractmethod
    def to_domain(self) -> GenericDomainModelType:
        """Create a domain model from this persistence model."""

    class Index:
        """
        Index metadata for the persistence model.

        Implementer must define this subclass.
        """

        name: str


class ESSearchResult(BaseModel):
    """Simple class for id<->score mapping in Elasticsearch search results."""

    id: uuid.UUID
    score: float
