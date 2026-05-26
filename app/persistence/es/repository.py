"""Generic repositories define expected functionality."""

import json
from abc import ABC
from collections.abc import AsyncGenerator, Sequence
from typing import Generic, Never
from uuid import UUID

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.dsl import AsyncSearch
from elasticsearch.dsl.exceptions import UnknownDslObject
from elasticsearch.dsl.query import Bool, MatchAll, Query, QueryString
from elasticsearch.dsl.response import Hit, Response
from elasticsearch.exceptions import BadRequestError
from opentelemetry import trace

from app.core.exceptions import (
    ESError,
    ESMalformedDocumentError,
    ESNotFoundError,
    ESQueryError,
)
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.repository import trace_repository_method
from app.persistence.es.generics import GenericESPersistenceType
from app.persistence.es.persistence import (
    ESFacetBucket,
    ESHit,
    ESSearchResult,
    ESSearchTotal,
    FilteredTermsAggSpec,
)
from app.persistence.generics import GenericDomainModelType
from app.persistence.repository import GenericAsyncRepository

tracer = trace.get_tracer(__name__)


class GenericAsyncESRepository(
    Generic[GenericDomainModelType, GenericESPersistenceType],
    GenericAsyncRepository[GenericDomainModelType, GenericESPersistenceType],  # type:ignore[type-var]
    ABC,
):
    """A generic implementation of a repository backed by SQLAlchemy."""

    _client: AsyncElasticsearch

    def __init__(
        self,
        client: AsyncElasticsearch,
        domain_cls: type[GenericDomainModelType],
        persistence_cls: type[GenericESPersistenceType],
    ) -> None:
        """
        Initialize the repository with the Elasticsearch client and model classes.

        :param client: The Elasticsearch client.
        :type client: AsyncElasticsearch
        :param domain_cls: The domain class of the model.
        :type domain_cls: type[GenericDomainModelType]
        :param persistence_cls: The Elasticsearch model class.
        :type persistence_cls: type[GenericESPersistenceType]
        """
        self._client = client
        self._persistence_cls = persistence_cls
        self._domain_cls = domain_cls
        self.system = "ES"

    @trace_repository_method(tracer)
    async def get_by_pk(
        self, pk: UUID, preload: list[Never] | None = None
    ) -> GenericDomainModelType:
        """
        Get a record using its primary key.

        :param pk: The primary key of the record to retrieve.
        :type pk: UUID
        :return: The retrieved record.
        :rtype: GenericDomainModelType
        """
        trace_attribute(Attributes.DB_PK, str(pk))
        if preload:
            msg = "Preloading is not supported in Elasticsearch repositories."
            raise ESError(msg)

        try:
            result = await self._persistence_cls.get(
                id=str(pk),
                using=self._client,
            )
        except NotFoundError:
            result = None

        if not result:
            detail = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise ESNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            )

        return result.to_domain()

    @trace_repository_method(tracer)
    async def add(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Add a record to the repository. If it already exists, it will be updated.

        :param record: The record to be persisted.
        :type record: GenericDomainModelType
        :return: The persisted record.
        :rtype: GenericDomainModelType
        """
        es_record = self._persistence_cls.from_domain(record)
        try:
            await es_record.save(using=self._client)
        except (BadRequestError, UnknownDslObject) as exc:
            # This is usually raised on incorrect percolation queries but
            # we raise it more generally.
            msg = f"Malformed Elasticsearch document: {record}. Error: {exc}."
            raise ESMalformedDocumentError(msg) from exc
        return record

    @trace_repository_method(tracer)
    async def add_bulk(
        self,
        get_records: AsyncGenerator[GenericDomainModelType, None],
    ) -> int:
        """
        Add multiple records to the repository in bulk, memory-efficiently.

        :param records: A generator of lists of records to be persisted.
        :type records: AsyncGenerator[GenericDomainModelType, None]
        """

        async def es_record_translation_generator() -> (
            AsyncGenerator[GenericESPersistenceType, None]
        ):
            """Translate domain records to Elasticsearch records."""
            async for record in get_records:
                yield self._persistence_cls.from_domain(record)

        added, _ = await self._persistence_cls.bulk(
            es_record_translation_generator(), using=self._client
        )
        return added

    @trace_repository_method(tracer)
    async def delete_by_pk(self, pk: UUID, *, fail_hard: bool = True) -> None:
        """
        Delete a record using its primary key.

        :param pk: The primary key of the record to delete.
        :type pk: UUID
        :param fail_hard: Whether to raise an error if the record does not exist.
        :type fail_hard: bool
        :return: None
        :rtype: None

        :raises ESNotFoundError: If the record does not exist.
        """
        trace_attribute(Attributes.DB_PK, str(pk))
        try:
            record = await self._persistence_cls.get(id=str(pk), using=self._client)
        except NotFoundError:
            record = None

        if record:
            await record.delete(using=self._client)
            return

        if fail_hard:
            detail = f"Unable to find {self._persistence_cls.__name__} with pk {pk}"
            raise ESNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            )

    def _parse_search_result(
        self, response: Response[Hit], page: int, *, parse_document: bool = False
    ) -> ESSearchResult:
        """
        Parse an Elasticsearch search response into a search result.

        :param response: The Elasticsearch search response.
        :type response: Response[Hit]
        :param parse_document: Whether to parse and include the full document.
        :type parse_document: bool
        :return: The parsed search result.
        :rtype: ESSearchResult
        """
        return ESSearchResult(
            hits=[
                ESHit(
                    id=hit.meta.id,
                    score=hit.meta.score,
                    document=self._persistence_cls.from_hit(hit).to_domain()
                    if parse_document
                    else None,
                )
                for hit in response.hits
            ],
            # ES DSL typing on response.hits is incorrect
            total=ESSearchTotal(
                value=response.hits.total.value,  # type: ignore[attr-defined]
                relation=response.hits.total.relation,  # type: ignore[attr-defined]
            ),
            page=page,
        )

    @trace_repository_method(tracer)
    async def search_with_query_string(  # noqa: PLR0913
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
        fields: Sequence[str] | None = None,
        sort: list[str] | None = None,
        filter_clauses: Sequence[Query] | None = None,
        *,
        parse_document: bool = False,
    ) -> ESSearchResult:
        """
        Search for records using a query string with optional structured filters.

        :param query: The query string to search with.
        :type query: str
        :param page: The page number to retrieve.
        :type page: int
        :param page_size: The number of records to return per page.
        :type page_size: int
        :param fields: The fields to search within. If None, searches all fields (unless
            the query specifies otherwise).
        :type fields: Sequence[str] | None
        :param sort: The sorting criteria for the search results.
        :type sort: list[str] | None
        :param filter_clauses: Structured DSL clauses ANDed with the query string under
            ``bool.filter`` (non-scoring). ``None`` or empty issues the bare query.
        :type filter_clauses: Sequence[Query] | None
        :param parse_document: Whether to retrieve the documents and include them in the
            hits as domain models.
        :type parse_document: bool
        :return: A list of matching records.
        :rtype: ESSearchResult
        """
        composed = self._compose_query(query, fields, filter_clauses)
        trace_attribute(Attributes.DB_QUERY, json.dumps(composed.to_dict()))
        search = (
            AsyncSearch(using=self._client, index=self._persistence_cls.Index.name)
            .extra(size=page_size)
            .extra(from_=(page - 1) * page_size)
            .query(composed)
        )
        if sort:
            search = search.sort(*sort)
        if not parse_document:
            search = search.source(includes=[])
        try:
            response = await search.execute()
        except BadRequestError as exc:
            msg = f"Elasticsearch query string search failed: {exc}."
            raise ESQueryError(msg) from exc
        return self._parse_search_result(response, page, parse_document=parse_document)

    @trace_repository_method(tracer)
    async def aggregate_terms(
        self,
        query: str,
        aggregate_on: Sequence[str],
        *,
        query_fields: Sequence[str] | None = None,
        filter_clauses: Sequence[Query] | None = None,
        max_buckets: int,
    ) -> dict[str, list[ESFacetBucket]]:
        """
        Run terms aggregations over documents matching a query string.

        Executes a single ``size=0`` search and returns one terms bucket list
        per requested field, ordered by document count descending.

        :param query: The query string filtering which documents are counted.
        :type query: str
        :param aggregate_on: ES field names to aggregate on.
        :type aggregate_on: Sequence[str]
        :param query_fields: Fields the query string should match against.
            ``None`` defers to the query string's own ``default_field``.
        :type query_fields: Sequence[str] | None
        :param filter_clauses: Structured DSL clauses ANDed with the query string under
            ``bool.filter``. ``None`` or empty issues the bare query.
        :type filter_clauses: Sequence[Query] | None
        :param max_buckets: Maximum buckets to return per aggregation.
        :type max_buckets: int
        :return: A mapping from each requested field name to its term buckets.
        :rtype: dict[str, list[ESFacetBucket]]
        """
        composed = self._compose_query(query, query_fields, filter_clauses)
        trace_attribute(Attributes.DB_QUERY, json.dumps(composed.to_dict()))
        search = (
            AsyncSearch(using=self._client, index=self._persistence_cls.Index.name)
            .extra(size=0)
            .query(composed)
            .source(includes=[])
        )
        for field in aggregate_on:
            search.aggs.bucket(field, "terms", field=field, size=max_buckets)
        try:
            response = await search.execute()
        except BadRequestError as exc:
            msg = f"Elasticsearch terms aggregation failed: {exc}."
            raise ESQueryError(msg) from exc
        return {
            field: [
                ESFacetBucket(key=str(bucket.key), count=bucket.doc_count)
                for bucket in response.aggregations[field].buckets
            ]
            for field in aggregate_on
        }

    @trace_repository_method(tracer)
    async def execute_filtered_terms_aggregations(
        self,
        query: str,
        *,
        query_fields: Sequence[str] | None = None,
        base_filter_clauses: Sequence[Query] = (),
        post_filter_clauses: Sequence[Query] = (),
        aggs: Sequence[FilteredTermsAggSpec],
    ) -> dict[str, list[ESFacetBucket]]:
        """
        Run multiple (optionally filter-wrapped) terms aggregations + post_filter.

        ``base_filter_clauses`` apply to both hits and aggregations under
        ``bool.filter``. ``post_filter_clauses`` restrict hits only, so
        aggregations can deliberately ignore a user-facing filter. Each spec
        returns its own bucket list keyed by ``name``.
        """
        composed = self._compose_query(query, query_fields, base_filter_clauses)
        search = (
            AsyncSearch(using=self._client, index=self._persistence_cls.Index.name)
            .extra(size=0)
            .query(composed)
            .source(includes=[])
        )
        if post_filter_clauses:
            search = search.post_filter(Bool(filter=list(post_filter_clauses)))
        for spec in aggs:
            outer_filter = (
                Bool(filter=list(spec.filter_clauses))
                if spec.filter_clauses
                else MatchAll()
            )
            outer = search.aggs.bucket(spec.name, "filter", filter=outer_filter)
            terms_kwargs: dict[str, object] = {
                "field": spec.field,
                "size": spec.size,
                "min_doc_count": spec.min_doc_count,
            }
            if spec.include is not None:
                terms_kwargs["include"] = list(spec.include)
            if spec.exclude is not None:
                terms_kwargs["exclude"] = list(spec.exclude)
            outer.bucket("terms_inner", "terms", **terms_kwargs)
        trace_attribute(Attributes.DB_QUERY, json.dumps(search.to_dict()))
        try:
            response = await search.execute()
        except BadRequestError as exc:
            msg = f"Elasticsearch filtered terms aggregation failed: {exc}."
            raise ESQueryError(msg) from exc
        return {
            spec.name: [
                ESFacetBucket(key=str(bucket.key), count=bucket.doc_count)
                for bucket in response.aggregations[spec.name].terms_inner.buckets
            ]
            for spec in aggs
        }

    def _compose_query(
        self,
        query_string: str,
        fields: Sequence[str] | None,
        filter_clauses: Sequence[Query] | None,
    ) -> Query:
        """Build the top-level query: a bare QueryString, or wrapped in bool.filter."""
        main = (
            QueryString(query=query_string, fields=fields)
            if fields
            else QueryString(query=query_string)
        )
        if not filter_clauses:
            return main
        return Bool(must=[main], filter=list(filter_clauses))
