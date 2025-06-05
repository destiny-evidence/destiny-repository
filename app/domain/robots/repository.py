"""Repositories for Robots and associated models."""

from abc import ABC

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.robots.models import Robot as DomainRobot
from app.domain.robots.sql import Robot as SQLRobot
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository


class RobotRepositoryBase(
    GenericAsyncRepository[DomainRobot, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Robots."""


class RobotSQLRepository(
    GenericAsyncSqlRepository[DomainRobot, SQLRobot],
    RobotRepositoryBase,
):
    """Concrete implementation of a repository for references using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainRobot,
            SQLRobot,
        )
