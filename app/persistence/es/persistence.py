"""Objects used to interface with SQL implementations."""

from abc import abstractmethod
from typing import Generic, Literal, Self
from uuid import UUID

from elasticsearch.dsl import AsyncDocument, InnerDoc
from elasticsearch.dsl.query import Query
from elasticsearch.dsl.response import Hit
from pydantic import BaseModel, ConfigDict, Field

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
        # If you're reading this because you've added nested documents to Elasticsearch
        # and you're wondering why the marshalling doesn't work, check out commit
        # 7c2cc7bef2bcb35fe18fa0606ad9fa84272144af.
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

    id: UUID
    score: float


class ESHit(BaseModel):
    """Represents a single hit from an Elasticsearch search result."""

    id: UUID = Field(description="The document ID.")
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


class ESFacetBucket(BaseModel):
    """A single bucket from a terms aggregation."""

    key: str = Field(description="The bucket key (the field value being counted).")
    count: int = Field(description="The number of documents in the bucket.")


class FilteredTermsAggSpec(BaseModel):
    """
    Structured spec for a (optionally filter-wrapped) terms aggregation.

    Used by :meth:`GenericAsyncESRepository.execute_filtered_terms_aggregations`
    to drive multi-aggregation searches where each aggregation can scope its
    document set independently of the main query.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str = Field(
        description="The aggregation name used as the bucket key in the response.",
    )
    field: str = Field(description="The ES field to aggregate on.")
    filter_clauses: tuple[Query, ...] = Field(
        default=(),
        description=(
            "If non-empty, the terms agg is wrapped in a ``filter`` agg with these "
            "clauses ANDed. Empty wraps in ``MatchAll`` so the response shape is "
            "uniform regardless of whether a per-agg filter is applied."
        ),
    )
    include: tuple[str, ...] | None = Field(
        default=None,
        description="Optional terms-agg ``include`` list.",
    )
    exclude: tuple[str, ...] | None = Field(
        default=None,
        description="Optional terms-agg ``exclude`` list.",
    )
    min_doc_count: int = Field(
        default=1,
        description=(
            "ES terms-agg ``min_doc_count``; set to 0 to surface zero-count buckets "
            "for values listed in ``include``."
        ),
    )
    size: int = Field(description="The maximum number of buckets to return.")
