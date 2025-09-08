"""Repositories for Robots and associated models."""

from abc import ABC

from opentelemetry import trace
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLIntegrityError, SQLNotFoundError
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.repository import trace_repository_method
from app.domain.robots.models.models import (
    Robot as DomainRobot,
)
from app.domain.robots.models.sql import (
    Robot as SQLRobot,
)
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository

tracer = trace.get_tracer(__name__)


class RobotRepositoryBase(
    GenericAsyncRepository[DomainRobot, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Robots."""


class RobotSQLRepository(
    GenericAsyncSqlRepository[DomainRobot, SQLRobot],
    RobotRepositoryBase,
):
    """Concrete implementation of a repository for robots using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainRobot,
            SQLRobot,
        )

    @trace_repository_method(tracer)
    async def merge(self, robot: DomainRobot) -> DomainRobot:
        """
        Merge a robot into the repository.

        We have a custom implementation of this for robots because we want to forbid
        updating the client_secret when merging.

        We also want to forbid the creation of robots except on add()

        If the record already exists in the database based on the PK, it will be
        updated. If it does not exist, it will be added.
        See also: https://docs.sqlalchemy.org/en/20/orm/session_state_management.html#merge-tips

        Args:
        - record (T): The record to be persisted.

        Raises:
        - SQLNotFoundError: If the robot does not already exist.
        - SQLIntegrityError: If the merge violates a unique constraint.

        """
        trace_attribute(Attributes.DB_PK, str(robot.id))
        self.trace_domain_object_id(robot)

        persistence = await self._session.get(self._persistence_cls, robot.id)
        if not persistence:
            detail = f"Unable to find {self._persistence_cls.__name__} "
            f"with pk {robot.id}"

            raise SQLNotFoundError(
                detail=detail,
                lookup_model=self._persistence_cls.__name__,
                lookup_type="id",
                lookup_value=robot.id,
            )

        persistence.base_url = str(robot.base_url)
        persistence.description = robot.description
        persistence.name = robot.name
        persistence.owner = robot.owner

        try:
            await self._session.flush()
        except IntegrityError as e:
            raise SQLIntegrityError.from_sqlalchemy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return persistence.to_domain()
