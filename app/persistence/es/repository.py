"""Generic repositories define expected functionality."""

import contextlib
from abc import ABC
from collections.abc import AsyncGenerator
from typing import Generic

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.dsl.exceptions import UnknownDslObject
from elasticsearch.exceptions import BadRequestError
from pydantic import UUID4

from app.core.exceptions import ESError, ESMalformedDocumentError, ESNotFoundError
from app.persistence.es.generics import GenericESPersistenceType
from app.persistence.generics import GenericDomainModelType
from app.persistence.repository import GenericAsyncRepository


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

    async def get_by_pk(
        self,
        pk: UUID4,
        preload: list[str] | None = None,
    ) -> GenericDomainModelType:
        """
        Get a record using its primary key.

        :param pk: The primary key of the record to retrieve.
        :type pk: UUID4
        :return: The retrieved record.
        :rtype: GenericDomainModelType
        """
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
        return await result.to_domain()

    async def add(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Add a record to the repository. If it already exists, it will be updated.

        :param record: The record to be persisted.
        :type record: GenericDomainModelType
        :return: The persisted record.
        :rtype: GenericDomainModelType
        """
        es_record = await self._persistence_cls.from_domain(record)
        try:
            await es_record.save(using=self._client)
        except (BadRequestError, UnknownDslObject) as exc:
            # This is usually raised on incorrect percolation queries but
            # we raise it more generally.
            msg = f"Malformed Elasticsearch document: {record}. Error: {exc}."
            raise ESMalformedDocumentError(msg) from exc
        return record

    async def add_bulk(
        self,
        get_records: AsyncGenerator[GenericDomainModelType, None],
    ) -> None:
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
                yield await self._persistence_cls.from_domain(record)

        await self._persistence_cls.bulk(
            es_record_translation_generator(), using=self._client
        )
