"""Service for searching references."""

import re

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

    default_search_fields = (
        "title",
        "abstract",
    )

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    def _query_string_specifies_fields(self, query_string: str) -> bool:
        """Check if the query string specifies fields to search."""
        # This is a relatively passive approach. If the user queries for a value
        # that matches this pattern (without specifying fields), it will just search all
        # fields instead of the defaults, so should always return a superset at worst.
        return bool(re.search(r"\w+:", query_string))

    async def search_with_query_string(
        self,
        query_string: str,
        page: int,
    ) -> ESSearchResult[Reference]:
        """Search for references matching the query string."""
        if not self._query_string_specifies_fields(query_string):
            return await self.es_uow.references.search_with_query_string(
                query_string, fields=self.default_search_fields
            )
        return await self.es_uow.references.search_with_query_string(
            query_string, page=page
        )
