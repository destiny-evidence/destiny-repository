"""Generic repositories define expected functionality."""

from abc import ABC
from typing import Generic

from elasticsearch import AsyncElasticsearch
from pydantic import UUID4

from app.core.exceptions import ESError
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
        pk: UUID4,  # noqa: ARG002
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

        msg = "ES yet to be implemented."
        raise NotImplementedError(msg)

    async def add(self, record: GenericDomainModelType) -> GenericDomainModelType:
        """
        Add a record to the repository.

        :param record: The record to be persisted.
        :type record: GenericDomainModelType
        :return: The persisted record.
        :rtype: GenericDomainModelType
        """
        msg = "ES yet to be implemented."
        raise NotImplementedError(msg)
