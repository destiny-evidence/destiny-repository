"""Base service class for domain business logic."""

from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork


class GenericService:
    """Base class for domain services."""

    def __init__(
        self, sql_uow: AsyncSqlUnitOfWork, es_uow: AsyncESUnitOfWork | None = None
    ) -> None:
        """
        Initialize the service with a unit of work.

        :param sql_uow: The SQL unit of work for database operations. This is the source
            of truth and is required.
        :type sql_uow: AsyncSqlUnitOfWork
        :param es_uow: The Elasticsearch unit of work for search operations, optional.
        :type es_uow: AsyncESUnitOfWork | None
        """
        self.sql_uow = sql_uow

        # This helps the static type checker understand that es_uow is not None if
        # we access it.
        if es_uow:
            self.es_uow: AsyncESUnitOfWork = es_uow
