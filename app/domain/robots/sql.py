"""Objects used to interface with SQL implementations."""

from typing import Self

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.robots.models import Robot as DomainRobot
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
