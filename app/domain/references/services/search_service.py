"""Service for searching references."""

from collections.abc import Sequence

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    FacetType,
    SearchQuery,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.persistence import ESFacetBucket, ESSearchResult
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class SearchService(GenericService[ReferenceAntiCorruptionService]):
    """
    Service for searching references.

    Thin orchestration over ``ReferenceESRepository``. The repository owns ES DSL
    construction; the service is where future query-shaping (vocabulary URI
    expansion, sibling-aware faceting setup for #703) will live, transforming
    domain ``SearchQuery`` objects before handing them to the repository.
    """

    # ES's default `track_total_hits` threshold. Pagination beyond this
    # produces `relation == "gte"` totals rather than exact counts. Lifting
    # the cap is tracked in destiny-repository#661.
    MAX_RESULT_WINDOW = 10_000

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    async def search_with_query(
        self,
        query: SearchQuery,
        page: int = 1,
        page_size: int = 20,
        sort: list[str] | None = None,
    ) -> ESSearchResult:
        """Search for references matching the given query specification."""
        return await self.es_uow.references.search(
            query,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    async def aggregate_facets(
        self,
        query: SearchQuery,
        facets: Sequence[FacetType],
    ) -> dict[FacetType, list[ESFacetBucket]]:
        """Count occurrences per facet over references matching ``query``."""
        return await self.es_uow.references.aggregate_facets(
            query,
            facets,
            max_buckets=settings.es_aggregation_max_buckets,
        )
