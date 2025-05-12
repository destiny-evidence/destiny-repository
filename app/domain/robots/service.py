"""The service for managing and interacting with robots."""

from app.domain.robots.models import Robots
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork


class RobotService(GenericService):
    """The service which manages interacting with robots."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork, robots: Robots) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)
        self.robots = robots
