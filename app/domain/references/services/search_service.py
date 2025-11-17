"""Service for searching references."""

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    AnnotationFilter,
    PublicationYearRange,
    Reference,
)
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

    def _build_publication_year_query_string_filter(
        self,
        publication_year_range: PublicationYearRange,
    ) -> str:
        """Build a publication year filter for Elasticsearch query string."""
        return (
            f"publication_year:[{publication_year_range.start or '*'} "
            f"TO {publication_year_range.end or '*'}]"
        )

    def _build_annotation_query_string_filter(
        self,
        annotation: AnnotationFilter,
    ) -> str:
        """
        Build an annotation filter for Elasticsearch query string.

        Examples:
        - For score filter: `scheme:>=0.8` (minimum bound on score)
        - For scheme and label: `annotations:"scheme/label"`
          - Quotes are used to handle any special characters.
        - For scheme only: `annotations:scheme*` (wildcard any label with the scheme)
          - Escaping is used on colons here as we can't wildcard in a quoted string.

        """
        if annotation.score is not None:
            field = annotation.scheme.replace(":", "_")
            if annotation.label:
                field += f"_{annotation.label}"
            return f"{field}:>={annotation.score}"
        if not annotation.label:
            return f"annotations:{annotation.scheme.replace(":", r"\:")}*"
        return f'annotations:"{annotation.scheme}/{annotation.label}"'

    async def search_with_query_string(
        self,
        query_string: str,
        page: int = 1,
        annotations: list[AnnotationFilter] | None = None,
        publication_year_range: PublicationYearRange | None = None,
        sort: list[str] | None = None,
    ) -> ESSearchResult[Reference]:
        """Search for references matching the query string."""
        global_filters: list[str] = []
        if publication_year_range:
            global_filters.append(
                self._build_publication_year_query_string_filter(
                    publication_year_range,
                )
            )
        if annotations:
            global_filters.extend(
                self._build_annotation_query_string_filter(annotation)
                for annotation in annotations
            )
        if global_filters:
            query_string = f"({query_string}) AND {' AND '.join(global_filters)}"
        return await self.es_uow.references.search_with_query_string(
            query_string, fields=self.default_search_fields, page=page, sort=sort
        )
