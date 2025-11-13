"""Generic repositories define expected functionality."""

import contextlib
from abc import ABC
from collections.abc import AsyncGenerator, Sequence
from typing import Generic, Never
from uuid import UUID

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.dsl import AsyncSearch
from elasticsearch.dsl.exceptions import UnknownDslObject
from elasticsearch.dsl.query import QueryString
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
from app.persistence.es.persistence import ESSearchResult, ESSearchTotal
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
        :type pk: UUID4
        :return: The retrieved record.
        :rtype: GenericDomainModelType
        """
        trace_attribute(Attributes.DB_PK, str(pk))
        if preload:
            msg = "Preloading is not supported in Elasticsearch repositories."
            raise ESError(msg)

        result = None
        with contextlib.suppress(NotFoundError):
            result = await self._persistence_cls.get(
                id=str(pk),
                using=self._client,
            )

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
    async def delete_by_pk(self, pk: UUID) -> None:
        """
        Delete a record using its primary key.

        :param pk: The primary key of the record to delete.
        :type pk: UUID4
        :return: None
        :rtype: None

        :raises ESNotFoundError: If the record does not exist.
        """
        trace_attribute(Attributes.DB_PK, str(pk))
        record = await self._persistence_cls.get(id=str(pk), using=self._client)
        if not record:
            raise ESNotFoundError(
                detail=f"Unable to find {self._persistence_cls.__name__} with pk {pk}",
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=pk,
            )
        await record.delete(using=self._client)

    def _parse_search_result(
        self, response: Response[Hit], page: int
    ) -> ESSearchResult[GenericDomainModelType]:
        """
        Parse an Elasticsearch search response into a search result.

        :param response: The Elasticsearch search response.
        :type response: Response[Hit]
        :return: The parsed search result.
        :rtype: ESSearchResult[GenericDomainModelType]
        """
        return ESSearchResult(
            hits=[
                self._persistence_cls.from_hit(hit).to_domain() for hit in response.hits
            ],
            # ES DSL typing on response.hits is incorrect
            total=ESSearchTotal(
                value=response.hits.total.value,  # type: ignore[attr-defined]
                relation=response.hits.total.relation,  # type: ignore[attr-defined]
            ),
            page=page,
        )

    @trace_repository_method(tracer)
    async def search_with_query_string(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
        fields: Sequence[str] | None = None,
        sort: list[str] | None = None,
    ) -> ESSearchResult[GenericDomainModelType]:
        """
        Search for records using a query string.

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
        :return: A list of matching records.
        :rtype: ESSearchResult[GenericDomainModelType]
        """
        trace_attribute(Attributes.DB_QUERY, query)
        search = (
            AsyncSearch(using=self._client)
            .doc_type(self._persistence_cls)
            .extra(size=page_size)
            .extra(from_=(page - 1) * page_size)
            .query(
                QueryString(query=query, fields=fields)
                if fields
                else QueryString(query=query)
            )
        )
        if fields:
            search = search.extra(fields=fields)
        if sort:
            search = search.sort(*sort)
        try:
            response = await search.execute()
        except BadRequestError as exc:
            msg = f"Elasticsearch query string search failed: {exc}."
            raise ESQueryError(msg) from exc
        return self._parse_search_result(response, page)
