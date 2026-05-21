"""Service for searching references."""

from collections.abc import Sequence
from typing import ClassVar

from destiny_sdk.references import FacetType
from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    AnnotationFilter,
    PublicationYearRange,
    SearchQuery,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.persistence import ESFacetBucket, ESSearchResult
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.utils.regex import escape_lucene_quoted_term

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class SearchService(GenericService[ReferenceAntiCorruptionService]):
    """Service for searching references."""

    default_search_fields = (
        "title",
        "abstract",
    )

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

        All user-supplied values are escaped to prevent query injection.

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
            return f"annotations:{annotation.scheme.replace(':', r'\:')}*"
        scheme = escape_lucene_quoted_term(annotation.scheme)
        label = escape_lucene_quoted_term(annotation.label)
        return f'annotations:"{scheme}/{label}"'

    # FacetType -> Elasticsearch field name. The service owns this mapping so
    # the repository layer stays generic in terms of which fields it aggregates.
    _FACET_FIELDS: ClassVar[dict[FacetType, str]] = {
        FacetType.CONCEPTS: "linked_data_concepts",
    }

    def _compose_query_string(self, query: SearchQuery) -> str:
        """Fold structured filters into a single Lucene query string."""
        global_filters: list[str] = []
        if query.publication_year_range:
            global_filters.append(
                self._build_publication_year_query_string_filter(
                    query.publication_year_range,
                )
            )
        global_filters.extend(
            self._build_annotation_query_string_filter(annotation)
            for annotation in query.annotation_filters
        )
        if not global_filters:
            return query.query_string
        return f"({query.query_string}) AND {' AND '.join(global_filters)}"

    async def search_with_query(
        self,
        query: SearchQuery,
        page: int = 1,
        page_size: int = 20,
        sort: list[str] | None = None,
    ) -> ESSearchResult:
        """Search for references matching the given query specification."""
        return await self.es_uow.references.search_with_query_string(
            self._compose_query_string(query),
            fields=self.default_search_fields,
            page=page,
            page_size=page_size,
            sort=sort,
            parse_document=False,
        )

    async def aggregate_facets(
        self,
        query: SearchQuery,
        facets: Sequence[FacetType],
    ) -> dict[FacetType, list[ESFacetBucket]]:
        """
        Compute facet bucket counts over the references matching ``query``.

        Naive implementation: each facet's counts are scoped by the *full*
        query (including any selections within that same facet). Tracked for a
        correct OR-sibling implementation in destiny-repository#703.
        """
        facet_to_field = {facet: self._FACET_FIELDS[facet] for facet in facets}
        buckets_by_field = await self.es_uow.references.aggregate_terms(
            self._compose_query_string(query),
            aggregate_on=list(facet_to_field.values()),
            query_fields=self.default_search_fields,
            max_buckets=settings.facet_max_buckets,
        )
        return {
            facet: buckets_by_field[field] for facet, field in facet_to_field.items()
        }
