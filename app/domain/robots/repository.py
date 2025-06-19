"""Repositories for Robots and associated models."""

from abc import ABC

from elasticsearch import AsyncElasticsearch
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLIntegrityError, SQLNotFoundError
from app.domain.robots.models.es import RobotAutomationPercolationDocument
from app.domain.robots.models.models import (
    Robot as DomainRobot,
)
from app.domain.robots.models.models import (
    RobotAutomation as DomainRobotAutomation,
)
from app.domain.robots.models.sql import (
    Robot as SQLRobot,
)
from app.domain.robots.models.sql import (
    RobotAutomation as SQLRobotAutomation,
)
from app.domain.robots.models.es import RobotAutomationPercolatable
from app.persistence.es.repository import GenericAsyncESRepository
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
    """Concrete implementation of a repository for robots using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainRobot,
            SQLRobot,
        )

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
        persistence = await self._session.get(self._persistence_cls, robot.id)
        if not persistence:
            detail = f"Unable to find {self._persistence_cls.__name__} "
            "with pk {robot.id}"

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
            raise SQLIntegrityError.from_sqlacademy_integrity_error(
                e, self._persistence_cls.__name__
            ) from e

        await self._session.refresh(persistence)
        return await persistence.to_domain()


class RobotAutomationRepositoryBase(
    GenericAsyncRepository[DomainRobotAutomation, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Robot Automations."""


class RobotAutomationSQLRepository(
    GenericAsyncSqlRepository[DomainRobotAutomation, SQLRobotAutomation],
    RobotAutomationRepositoryBase,
):
    """Concrete implementation of a repository for robot automations using SQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainRobotAutomation,
            SQLRobotAutomation,
        )


class RobotAutomationESRepository(
    GenericAsyncESRepository[DomainRobotAutomation, RobotAutomationPercolationDocument],
    RobotAutomationRepositoryBase,
):
    """Concrete implementation for robot automations using Elasticsearch."""

    def __init__(self, client: AsyncElasticsearch) -> None:
        """Initialize the repository with the Elasticsearch client."""
        super().__init__(
            client,
            DomainRobotAutomation,
            RobotAutomationPercolationDocument,
        )

    async def percolate(
        self,
        documents: list[RobotAutomationPercolatable],
    ):
        """
        Percolate documents against the percolation queries in Elasticsearch.

        :param documents: A list of documents to percolate.
        :type documents: list[RobotAutomationPercolatable]
        :return: The results of the percolation.
        :rtype: TODO
        """
        percolation = await (
            self._persistence_cls.search()
            .using(self._client)
            .query(
                {
                    "percolate": {
                        "field": "query",
                        "documents": [document.to_dict() for document in documents],
                    }
                }
            )
            .execute()
        )
