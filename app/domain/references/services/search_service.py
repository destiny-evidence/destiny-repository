"""Service for searching references."""

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import Reference
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.persistence import ESSearchResult
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class SearchService(GenericService[ReferenceAntiCorruptionService]):
    """Service for searching references."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    async def search_with_query_string(
        self,
        query_string: str,
    ) -> ESSearchResult[Reference]:
        """Search for references matching the query string."""
        return await self.es_uow.references.search_with_query_string(query_string)
