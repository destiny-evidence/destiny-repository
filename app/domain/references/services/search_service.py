"""Service for searching references."""

from collections.abc import Iterable, Sequence

from opentelemetry import trace

from app.core.config import get_settings
from app.core.exceptions import SiblingGroupingError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    FacetType,
    LinkedDataConceptFilter,
    SearchQuery,
    SiblingGroup,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.external.vocabulary.client import (
    VocabularyArtifactClient,
    get_vocabulary_artifact_client,
)
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
        vocab_client: VocabularyArtifactClient | None = None,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)
        self._vocab_client = vocab_client or get_vocabulary_artifact_client()

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
        """Count occurrences per facet over references matching ``query``."""
        max_buckets = settings.es_aggregation_max_buckets
        sibling_groups_by_facet: dict[FacetType, tuple[SiblingGroup, ...]] = {}
        if query.linked_data_concept_filters and FacetType.CONCEPTS in facets:
            if not vocabulary_uri:
                msg = (
                    "`vocabulary=` is required when filtering on concepts and "
                    "requesting the `concepts` facet."
                )
                raise SiblingGroupingError(msg)
            groups = await self._resolve_concept_sibling_groups(
                vocabulary_uri, query.linked_data_concept_filters
            )
            self._validate_groups_against_max_buckets(groups, max_buckets)
            sibling_groups_by_facet[FacetType.CONCEPTS] = groups
        if query.linked_data_country_filters and FacetType.COUNTRIES in facets:
            sibling_groups_by_facet[FacetType.COUNTRIES] = (
                self._universal_sibling_groups(
                    tuple(f.country_codes) for f in query.linked_data_country_filters
                )
            )
        if (
            query.linked_data_country_wb_region_filters
            and FacetType.COUNTRY_WB_REGIONS in facets
        ):
            sibling_groups_by_facet[FacetType.COUNTRY_WB_REGIONS] = (
                self._universal_sibling_groups(
                    tuple(f.region_ids)
                    for f in query.linked_data_country_wb_region_filters
                )
            )
        return await self.es_uow.references.aggregate_facets(
            query,
            facets,
            sibling_groups_by_facet=sibling_groups_by_facet,
            max_buckets=max_buckets,
        )

    @staticmethod
    def _validate_groups_against_max_buckets(
        groups: Sequence[SiblingGroup], max_buckets: int
    ) -> None:
        """Refuse if any enumerated group would exceed ``max_buckets``."""
        for i, group in enumerate(groups):
            siblings = group.siblings_including_selected
            if siblings is None:
                continue
            if len(siblings) > max_buckets:
                msg = (
                    f"Sibling group {i} has {len(siblings)} values (selected "
                    f"+ siblings), exceeding max_buckets={max_buckets}. Counts "
                    "would be silently truncated; refusing."
                )
                raise SiblingGroupingError(msg)

    @staticmethod
    def _universal_sibling_groups(
        selections: Iterable[tuple[str, ...]],
    ) -> tuple[SiblingGroup, ...]:
        """Build universal-mode groups (siblings = entire field)."""
        groups = tuple(
            SiblingGroup(selected=selected, siblings_including_selected=None)
            for selected in selections
        )
        if len(groups) > 1:
            msg = (
                "Multiple AND'd filters are not supported when requesting "
                "sibling-aware counts for this facet. Combine them into a single OR'd "
                "filter."
            )
            raise SiblingGroupingError(msg)
        return groups

    async def _resolve_concept_sibling_groups(
        self,
        vocabulary_uri: str,
        concept_filters: Sequence[LinkedDataConceptFilter],
    ) -> tuple[SiblingGroup, ...]:
        """Resolve concept filters into sibling groups; raises on rule violations."""
        siblings_map = await self._vocab_client.get_concept_siblings(vocabulary_uri)
        groups: list[SiblingGroup] = []
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
                SiblingGroup(
                    selected=tuple(concept_filter.concept_uris),
                    siblings_including_selected=sibling_set,
                )
            )
        resolved_siblings: list[frozenset[str]] = []
        for group in groups:
            if group.siblings_including_selected is None:
                msg = "_resolve_concept_sibling_groups produced a universal group."
                raise ValueError(msg)
            resolved_siblings.append(group.siblings_including_selected)
        for i, sib_a in enumerate(resolved_siblings):
            for sib_b in resolved_siblings[i + 1 :]:
                overlap = sib_a & sib_b
                if overlap:
                    msg = (
                        "Two concept filters share a sibling set. Overlap: "
                        f"{sorted(overlap)}"
                    )
                    raise SiblingGroupingError(msg)
        return tuple(groups)
