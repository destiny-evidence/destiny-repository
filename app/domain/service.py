"""Base service class for domain business logic."""

from typing import Generic, TypeVar

from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork


class GenericAntiCorruptionService:
    """
    Base class for anti-corruption services that handle external system translations.

    This service acts as a boundary between the domain and external systems (like SDKs),
    ensuring that external concerns don't leak into the domain models.
    """


GenericAntiCorruptionServiceType = TypeVar(
    "GenericAntiCorruptionServiceType", bound=GenericAntiCorruptionService
)


class GenericService(Generic[GenericAntiCorruptionServiceType]):
    """Base class for domain services."""

    def __init__(
        self,
        anti_corruption_service: GenericAntiCorruptionServiceType,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork | None = None,
    ) -> None:
        """
        Initialize the service with a unit of work.

        :param anti_corruption_service: The anti-corruption service for external
            system translations.
        :type anti_corruption_service: GenericAntiCorruptionServiceType
        :param sql_uow: The SQL unit of work for database operations. This is the source
            of truth and is required.
        :type sql_uow: AsyncSqlUnitOfWork
        :param es_uow: The Elasticsearch unit of work for search operations, optional.
        :type es_uow: AsyncESUnitOfWork | None
        """
        self._anti_corruption_service = anti_corruption_service
        self.sql_uow = sql_uow

        # This helps the static type checker understand that es_uow is not None if
        # we access it.
        if es_uow:
            self.es_uow: AsyncESUnitOfWork = es_uow
