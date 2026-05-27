"""Service for searching references."""

from collections.abc import Sequence

from opentelemetry import trace

from app.core.config import get_settings
from app.core.exceptions import SiblingGroupingError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    ConceptSiblingGroup,
    FacetType,
    LinkedDataConceptFilter,
    SearchQuery,
    SiblingGrouping,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.external.vocabulary.client import VocabularyArtifactClient
from app.persistence.es.persistence import ESFacetBucket, ESSearchResult
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class SearchService(GenericService[ReferenceAntiCorruptionService]):
    """Service for searching references."""

    # ES's default `track_total_hits` threshold. Pagination beyond this
    # produces `relation == "gte"` totals rather than exact counts. Lifting
    # the cap is tracked in destiny-repository#661.
    MAX_RESULT_WINDOW = 10_000

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
        vocab_client: VocabularyArtifactClient,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)
        self._vocab_client = vocab_client

    async def search(
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
        vocabulary_uri: str | None,
    ) -> dict[FacetType, list[ESFacetBucket]]:
        """Count per facet; sibling-aware when concepts filter + facet are both set."""
        max_buckets = settings.es_aggregation_max_buckets
        sibling_required = (
            bool(query.linked_data_concept_filters) and FacetType.CONCEPTS in facets
        )
        if not sibling_required:
            return await self.es_uow.references.aggregate_facets_naive(
                query, facets, max_buckets=max_buckets
            )
        if not vocabulary_uri:
            msg = (
                "`vocabulary=` is required when filtering on concepts and "
                "requesting the `concepts` facet."
            )
            raise SiblingGroupingError(msg)
        grouping = await self._resolve_sibling_grouping(
            vocabulary_uri, query.linked_data_concept_filters
        )
        self._validate_grouping_against_max_buckets(grouping, max_buckets)
        return await self.es_uow.references.aggregate_facets_sibling_aware(
            query, grouping, max_buckets=max_buckets
        )

    @staticmethod
    def _validate_grouping_against_max_buckets(
        grouping: SiblingGrouping, max_buckets: int
    ) -> None:
        """Refuse if any group's sibling set would exceed ``max_buckets``."""
        for i, group in enumerate(grouping.groups):
            include_size = len(group.siblings_including_selected)
            if include_size > max_buckets:
                msg = (
                    f"Sibling group {i} has {include_size} concepts (selected "
                    f"+ siblings), exceeding max_buckets={max_buckets}. Counts "
                    "would be silently truncated; refusing."
                )
                raise SiblingGroupingError(msg)

    async def _resolve_sibling_grouping(
        self,
        vocabulary_uri: str,
        concept_filters: Sequence[LinkedDataConceptFilter],
    ) -> SiblingGrouping:
        """Group concept filters by sibling sets; raises on rule violations."""
        siblings_map = await self._vocab_client.get_concept_siblings(vocabulary_uri)
        groups: list[ConceptSiblingGroup] = []
        for concept_filter in concept_filters:
            unresolved = [
                uri for uri in concept_filter.concept_uris if uri not in siblings_map
            ]
            if unresolved:
                msg = (
                    f"Concept URI(s) not found in vocabulary {vocabulary_uri!r}: "
                    f"{', '.join(unresolved)}"
                )
                raise SiblingGroupingError(msg)
            sibling_sets = {siblings_map[uri] for uri in concept_filter.concept_uris}
            if len(sibling_sets) != 1:
                msg = (
                    "Concept filter mixes URIs from different sibling sets: "
                    f"{concept_filter.concept_uris}"
                )
                raise SiblingGroupingError(msg)
            (sibling_set,) = sibling_sets
            groups.append(
                ConceptSiblingGroup(
                    source_filter=concept_filter,
                    siblings_including_selected=sibling_set,
                )
            )
        for i, group in enumerate(groups):
            for other in groups[i + 1 :]:
                overlap = (
                    group.siblings_including_selected
                    & other.siblings_including_selected
                )
                if overlap:
                    msg = (
                        "Two concept filters share a sibling set. Overlap: "
                        f"{sorted(overlap)}"
                    )
                    raise SiblingGroupingError(msg)
        return SiblingGrouping(groups=tuple(groups))
