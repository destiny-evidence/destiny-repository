"""Service for searching references."""

from collections.abc import Sequence
from typing import ClassVar

from elasticsearch.dsl.query import Prefix, Query, Range, Term, Terms
from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    AnnotationFilter,
    FacetType,
    LinkedDataConceptFilter,
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

    _FACET_FIELDS: ClassVar[dict[FacetType, str]] = {
        FacetType.CONCEPTS: "linked_data_concepts",
    }

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    def _build_publication_year_clause(
        self,
        publication_year_range: PublicationYearRange,
    ) -> Query | None:
        """Range clause on ``publication_year``; ``None`` if both bounds are unset."""
        bounds: dict[str, int] = {}
        if publication_year_range.start is not None:
            bounds["gte"] = publication_year_range.start
        if publication_year_range.end is not None:
            bounds["lte"] = publication_year_range.end
        if not bounds:
            return None
        return Range(publication_year=bounds)

    def _build_linked_data_concept_clause(
        self,
        concept_filter: LinkedDataConceptFilter,
    ) -> Query:
        """Terms clause matching any of the listed concept URIs (OR semantics)."""
        return Terms(linked_data_concepts=concept_filter.concept_uris)

    def _build_annotation_clause(self, annotation: AnnotationFilter) -> Query:
        """
        Build a structured DSL clause for an annotation filter.

        Three cases mirror the original Lucene builder:

        - ``score`` set: range on the dynamic ``<scheme>[_<label>]`` numeric field,
          with ``:`` in the scheme replaced by ``_`` (e.g. ``inclusion_destiny``).
        - scheme only, no score: prefix match on the ``annotations`` keyword field,
          matching any ``<scheme>/...`` annotation.
        - scheme + label: exact term match on ``annotations``.
        """
        if annotation.score is not None:
            field = annotation.scheme.replace(":", "_")
            if annotation.label:
                field += f"_{annotation.label}"
            return Range(**{field: {"gte": annotation.score}})
        if not annotation.label:
            return Prefix(annotations=f"{annotation.scheme}/")
        return Term(annotations=f"{annotation.scheme}/{annotation.label}")

    def _build_filter_clauses(self, query: SearchQuery) -> list[Query]:
        """Translate a SearchQuery's structured filters into bool.filter clauses."""
        clauses: list[Query] = []
        if query.publication_year_range and (
            clause := self._build_publication_year_clause(query.publication_year_range)
        ):
            clauses.append(clause)
        clauses.extend(
            self._build_annotation_clause(annotation)
            for annotation in query.annotation_filters
        )
        clauses.extend(
            self._build_linked_data_concept_clause(concept_filter)
            for concept_filter in query.linked_data_concept_filters
        )
        return clauses

    async def search_with_query(
        self,
        query: SearchQuery,
        page: int = 1,
        page_size: int = 20,
        sort: list[str] | None = None,
    ) -> ESSearchResult:
        """Search for references matching the given query specification."""
        return await self.es_uow.references.search_with_query_string(
            query.query_string,
            fields=self.default_search_fields,
            page=page,
            page_size=page_size,
            sort=sort,
            filter_clauses=self._build_filter_clauses(query),
            parse_document=False,
        )

    async def aggregate_facets(
        self,
        query: SearchQuery,
        facets: Sequence[FacetType],
    ) -> dict[FacetType, list[ESFacetBucket]]:
        """
        Count occurrences per facet over references matching ``query``.

        Naive: counts are scoped by the full query, so filters within a facet
        contribute to that facet's own counts. See destiny-repository#703.
        """
        facet_to_field = {facet: self._FACET_FIELDS[facet] for facet in facets}
        buckets_by_field = await self.es_uow.references.aggregate_terms(
            query.query_string,
            aggregate_on=list(facet_to_field.values()),
            query_fields=self.default_search_fields,
            filter_clauses=self._build_filter_clauses(query),
            max_buckets=settings.es_aggregation_max_buckets,
        )
        return {
            facet: buckets_by_field[field] for facet, field in facet_to_field.items()
        }
