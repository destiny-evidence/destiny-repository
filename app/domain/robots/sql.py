"""Objects used to interface with SQL implementations."""

from typing import Self

from destiny_sdk.enhancements import EnhancementType
from destiny_sdk.identifiers import ExternalIdentifierType
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
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

    robot_base_url: Mapped[str] = mapped_column(String, nullable=False)

    robot_secret: Mapped[str] = mapped_column(String, nullable=False)

    dependent_enhancements: Mapped[list[EnhancementType]] = mapped_column(
        ARRAY(
            ENUM(
                *[enhancement_type.value for enhancement_type in EnhancementType],
                name="enhancement_type",
            )
        ),
        nullable=True,
    )

    dependent_identifiers: Mapped[list[ExternalIdentifierType]] = mapped_column(
        ARRAY(
            ENUM(
                *[identifier_type.value for identifier_type in ExternalIdentifierType],
                name="identifier_type",
            )
        ),
        nullable=True,
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainRobot) -> Self:
        """Create a persistence model from a domain Robot object."""
        return cls(
            id=domain_obj.id,
            robot_base_url=str(domain_obj.robot_base_url),
            robot_secret=domain_obj.robot_secret.get_secret_value(),
            dependent_enhancements=[
                enhancement_type.value
                for enhancement_type in domain_obj.dependent_enhancements
            ]
            if domain_obj.dependent_enhancements
            else None,
            dependent_identifiers=[
                identifier_type.value
                for identifier_type in domain_obj.dependent_identifiers
            ]
            if domain_obj.dependent_identifiers
            else None,
        )

    async def to_domain(
        self,
        preload: list[str] | None = None,  # noqa: ARG002
    ) -> DomainRobot:
        """Convert the persistence model indo a Domain Robot object."""
        return DomainRobot(
            id=self.id,
            robot_base_url=self.robot_base_url,
            robot_secret=self.robot_secret,
            dependent_enhancements=self.dependent_enhancements
            if self.dependent_enhancements
            else [],
            dependent_identifiers=self.dependent_identifiers
            if self.dependent_identifiers
            else [],
        )
