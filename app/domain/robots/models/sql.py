"""Objects used to interface with SQL implementations."""

import uuid
from typing import Any, Self

from sqlalchemy import UUID, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.robots.models.models import (
    Robot as DomainRobot,
)
from app.domain.robots.models.models import (
    RobotAutomation as DomainRobotAutomation,
)
from app.persistence.sql.persistence import GenericSQLPersistence


class Robot(GenericSQLPersistence[DomainRobot]):
    """
    SQL Persistence model for a Robot.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "robot"

    base_url: Mapped[str] = mapped_column(String, nullable=False)

    client_secret: Mapped[str] = mapped_column(String, nullable=False)

    description: Mapped[str] = mapped_column(String, nullable=False)

    name: Mapped[str] = mapped_column(String, nullable=False)

    owner: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "name",
            name="uix_robot",
        ),
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainRobot) -> Self:
        """Create a persistence model from a domain Robot object."""
        if not domain_obj.client_secret:
            msg = "Cannot convert domain robot without client secret for persistence."
            raise RuntimeError(msg)
        return cls(
            id=domain_obj.id,
            base_url=str(domain_obj.base_url),
            client_secret=domain_obj.client_secret.get_secret_value(),
            description=domain_obj.description,
            name=domain_obj.name,
            owner=domain_obj.owner,
        )

    async def to_domain(
        self,
        preload: list[str] | None = None,  # noqa: ARG002
    ) -> DomainRobot:
        """Convert the persistence model indo a Domain Robot object."""
        return DomainRobot(
            id=self.id,
            base_url=self.base_url,
            client_secret=self.client_secret,
            description=self.description,
            name=self.name,
            owner=self.owner,
        )


class RobotAutomation(GenericSQLPersistence[DomainRobotAutomation]):
    """
    SQL Persistence model for a Robot Automation.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "robot_automation"

    robot_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("robot.id"), nullable=False
    )

    query: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "robot_id",
            "query",
            name="uix_robot_automation",
        ),
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainRobotAutomation) -> Self:
        """Create a persistence model from a domain RobotAutomation object."""
        return cls(
            id=domain_obj.id,
            robot_id=domain_obj.robot_id,
            query=domain_obj.query,
        )

    async def to_domain(
        self,
        preload: list[str] | None = None,  # noqa: ARG002
    ) -> DomainRobotAutomation:
        """Convert the persistence model into a Domain RobotAutomation object."""
        return DomainRobotAutomation(
            id=self.id,
            robot_id=self.robot_id,
            query=self.query,
        )
