"""Base service class for domain business logic."""

from app.persistence.sql.uow import AsyncSqlUnitOfWork


class GenericService:
    """Base class for domain services."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        self.sql_uow = sql_uow
