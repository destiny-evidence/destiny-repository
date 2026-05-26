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
        """
        Count occurrences per facet over references matching ``query``.

        When ``vocabulary_uri`` is supplied and the request asks for the
        ``CONCEPTS`` facet with concept filters present, sibling-aware
        counting kicks in: each ``concept=`` filter is treated as its own
        sibling group whose siblings come from the vocabulary, and the
        aggregation isolates each group's count from the others. Otherwise,
        an empty grouping triggers the naive (today's) aggregation path.

        :raises SiblingGroupingError: If the user's concept filters can't be
            cleanly grouped against the vocabulary — see the rule constraints
            in :func:`_resolve_sibling_grouping`.
        """
        grouping: SiblingGrouping
        if (
            vocabulary_uri
            and FacetType.CONCEPTS in facets
            and query.linked_data_concept_filters
        ):
            grouping = await self._resolve_sibling_grouping(
                vocabulary_uri,
                query.linked_data_concept_filters,
            )
        else:
            grouping = SiblingGrouping()
        return await self.es_uow.references.aggregate_facets(
            query,
            facets,
            grouping,
            max_buckets=settings.es_aggregation_max_buckets,
        )

    async def _resolve_sibling_grouping(
        self,
        vocabulary_uri: str,
        concept_filters: Sequence[LinkedDataConceptFilter],
    ) -> SiblingGrouping:
        """
        Group concept filters by their sibling sets in ``vocabulary_uri``.

        Enforces three rules; any violation surfaces as a 400 via
        :class:`SiblingGroupingError`:

        - **(a)** Every URI inside a single filter must share a sibling set.
        - **(b)** Across filters, the per-filter sibling sets must be disjoint.
        - **(c)** Every URI must resolve in the supplied vocabulary.

        The user's ``concept=`` partition is preserved verbatim — one
        :class:`ConceptSiblingGroup` per :class:`LinkedDataConceptFilter`.
        """
        siblings_map = await self._vocab_client.get_concept_siblings(vocabulary_uri)
        groups: list[ConceptSiblingGroup] = []
        for concept_filter in concept_filters:
            # Rule (c): every URI must be in the vocabulary.
            unresolved = [
                uri for uri in concept_filter.concept_uris if uri not in siblings_map
            ]
            if unresolved:
                msg = (
                    "Concept URI(s) not found in supplied vocabulary "
                    f"{vocabulary_uri!r}: {', '.join(unresolved)}"
                )
                raise SiblingGroupingError(msg)
            # Rule (a): URIs inside one filter must share a sibling set.
            sibling_sets = {siblings_map[uri] for uri in concept_filter.concept_uris}
            if len(sibling_sets) != 1:
                msg = (
                    "Concept filter mixes URIs from different sibling sets; siblings "
                    "should be grouped in one filter and unrelated concepts split "
                    f"across separate filters. URIs: {concept_filter.concept_uris}"
                )
                raise SiblingGroupingError(msg)
            (sibling_set,) = sibling_sets
            groups.append(
                ConceptSiblingGroup(
                    source_filter=concept_filter,
                    siblings_including_selected=sibling_set,
                )
            )
        # Rule (b): per-filter sibling sets must be disjoint.
        for i, group in enumerate(groups):
            for other in groups[i + 1 :]:
                overlap = (
                    group.siblings_including_selected
                    & other.siblings_including_selected
                )
                if overlap:
                    msg = (
                        "Two concept filters share a sibling set; siblings should "
                        "be grouped in a single ``concept=`` parameter. Overlap: "
                        f"{sorted(overlap)}"
                    )
                    raise SiblingGroupingError(msg)
        all_grouped_uris = frozenset().union(
            *(group.siblings_including_selected for group in groups)
        )
        return SiblingGrouping(
            groups=tuple(groups),
            all_grouped_uris=all_grouped_uris,
        )
