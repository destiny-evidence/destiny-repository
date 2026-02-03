"""Objects used to interface with SQL implementations."""

from abc import abstractmethod
from typing import Generic, Literal, Self

from elasticsearch.dsl import AsyncDocument, InnerDoc
from elasticsearch.dsl.response import Hit
from pydantic import UUID4, BaseModel, Field

from app.domain.base import SQLAttributeMixin
from app.persistence.generics import GenericDomainModelType


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

    @classmethod
    def from_hit(cls, hit: Hit) -> Self:
        """Create a persistence model from an Elasticsearch Hit object."""
        return cls(
            **hit.to_dict(),
            meta={"id": hit.meta.id},
        )

    class Index:
        """
        Index metadata for the persistence model.

        Implementer must define this subclass.
        """

        name: str


class GenericNestedDocument(InnerDoc):
    """Generic implementation for an elasticsearch nested document."""

    @classmethod
    def from_hit(cls, hits: dict) -> Self:
        """Create a persistence model from an Elasticsearch Hit dict."""
        return cls(**hits)


class ESScoreResult(BaseModel):
    """Simple class for id<->score mapping in Elasticsearch search results."""

    id: UUID4
    score: float


class ESHit(BaseModel):
    """Represents a single hit from an Elasticsearch search result."""

    id: UUID4 = Field(description="The document ID.")
    score: float | None = Field(
        default=None,
        description="The relevance score of the hit.",
    )
    document: SQLAttributeMixin | None = Field(
        default=None,
        description="The source document, if requested.",
    )


class ESSearchTotal(BaseModel):
    """
    Class for total results in Elasticsearch search results.

    Unless otherwise specified in the request, Elasticsearch will stop counting after
    10,000 and return a lower bound with relation "gte".
    """

    value: int = Field(description="The total number of results found.")
    relation: Literal["eq", "gte"] = Field(
        description=(
            "Indicates whether the total count is exact or just a lower bound."
        ),
    )


class ESSearchResult(BaseModel):
    """Wrapping class for Elasticsearch search results."""

    hits: list[ESHit] = Field(
        default_factory=list,
        description="The list of hits returned from the search query.",
    )
    total: ESSearchTotal = Field(
        description="The total number of results matching the search query.",
    )
    page: int = Field(
        description="The page number of the results.",
    )
