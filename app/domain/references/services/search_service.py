"""Service for searching references."""

from collections.abc import Iterable, Sequence
from typing import ClassVar

from opentelemetry import trace

from app.core.config import get_settings
from app.core.exceptions import ParseError, SiblingGroupingError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    CrossFacetAxis,
    CrossFacetCell,
    FacetType,
    LinkedDataConceptFilter,
    SearchQuery,
    SiblingGroup,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.world_bank_regions import WORLD_BANK_REGIONS
from app.domain.service import GenericService
from app.external.vocabulary.client import (
    VocabularyArtifactClient,
    get_vocabulary_artifact_client,
)
from app.persistence.es.persistence import (
    ESFacetBucket,
    ESSearchResult,
    ESSearchTotal,
)
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

    # The terms `size` for each literal (non-scheme) axis. A token is a literal axis
    # iff `FacetType(token)` is one of these; their value sets are small and bounded.
    _LITERAL_AXIS_SIZES: ClassVar[dict[FacetType, int]] = {
        FacetType.COUNTRIES: 256,  # conservative bound on the ~249 ISO 3166-1 codes
        FacetType.COUNTRY_WB_REGIONS: len(WORLD_BANK_REGIONS),
    }

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

    async def aggregate_cross_facet(
        self,
        query: SearchQuery,
        row_token: str,
        column_token: str,
        vocabulary_uri: str | None,
    ) -> tuple[list[CrossFacetCell], ESSearchTotal]:
        """
        Cross-tabulate two axes over references matching ``query``.

        Each axis is a literal axis or a concept-scheme URI (scoped to its members
        via ``vocabulary_uri``). Returns the non-zero cells and the exact grand total.
        """
        scheme_members: dict[str, frozenset[str]] | None = None
        if vocabulary_uri and (
            self._literal_axis_facet(row_token) is None
            or self._literal_axis_facet(column_token) is None
        ):
            scheme_members = await self._vocab_client.get_scheme_members(vocabulary_uri)
        row = self._resolve_cross_facet_axis(row_token, vocabulary_uri, scheme_members)
        column = self._resolve_cross_facet_axis(
            column_token, vocabulary_uri, scheme_members
        )
        self._validate_cross_facet_cell_count(
            row, column, settings.es_cross_facet_max_cells
        )
        return await self.es_uow.references.aggregate_cross_facet(query, row, column)

    @classmethod
    def _literal_axis_facet(cls, token: str) -> FacetType | None:
        """Return the FacetType for a literal (non-scheme) axis token, else None."""
        try:
            facet = FacetType(token)
        except ValueError:
            return None
        return facet if facet in cls._LITERAL_AXIS_SIZES else None

    @classmethod
    def _resolve_cross_facet_axis(
        cls,
        token: str,
        vocabulary_uri: str | None,
        scheme_members: dict[str, frozenset[str]] | None,
    ) -> CrossFacetAxis:
        """Resolve an axis token into a ``CrossFacetAxis``, or raise ``ParseError``."""
        literal_facet = cls._literal_axis_facet(token)
        if literal_facet is not None:
            return CrossFacetAxis(
                token=token,
                facet_type=literal_facet,
                include=None,
                size=cls._LITERAL_AXIS_SIZES[literal_facet],
            )
        # A non-literal token is treated as a concept-scheme URI.
        if not vocabulary_uri or scheme_members is None:
            msg = (
                "`vocabulary=` is required when an axis is a concept scheme: "
                f"{token!r}."
            )
            raise ParseError(msg)
        members = scheme_members.get(token)
        if not members:
            msg = (
                f"Concept scheme {token!r} has no members in vocabulary "
                f"{vocabulary_uri!r}."
            )
            raise ParseError(msg)
        return CrossFacetAxis(
            token=token,
            facet_type=FacetType.CONCEPTS,
            include=members,
            size=len(members),
        )

    @staticmethod
    def _validate_cross_facet_cell_count(
        row: CrossFacetAxis, column: CrossFacetAxis, max_cells: int
    ) -> None:
        """Refuse a matrix whose cell count would exceed ``max_cells``."""
        cells = row.size * column.size
        if cells > max_cells:
            msg = (
                f"Cross-facet matrix would request {cells} cells ({row.size} x "
                f"{column.size}), exceeding the limit of {max_cells}. Choose axes "
                "with fewer members."
            )
            raise ParseError(msg)

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
        """
        Resolve concept filters into one sibling group per scheme.

        Raises on rule violations: one scheme per filter, distinct schemes across
        filters.
        """
        members_by_concept = await self._vocab_client.get_concept_scheme_members(
            vocabulary_uri
        )
        groups: list[SiblingGroup] = []
        for concept_filter in concept_filters:
            unresolved = [
                uri
                for uri in concept_filter.concept_uris
                if uri not in members_by_concept
            ]
            if unresolved:
                msg = (
                    f"Concept URI(s) not found in vocabulary {vocabulary_uri!r}: "
                    f"{', '.join(unresolved)}"
                )
                raise SiblingGroupingError(msg)
            schemes = {members_by_concept[uri] for uri in concept_filter.concept_uris}
            if len(schemes) != 1:
                msg = (
                    "Concept filter mixes URIs from different schemes: "
                    f"{concept_filter.concept_uris}"
                )
                raise SiblingGroupingError(msg)
            (scheme_members,) = schemes
            groups.append(
                SiblingGroup(
                    selected=tuple(concept_filter.concept_uris),
                    siblings_including_selected=scheme_members,
                )
            )
        members_per_group: list[frozenset[str]] = []
        for group in groups:
            if group.siblings_including_selected is None:
                msg = "_resolve_concept_sibling_groups produced a universal group."
                raise ValueError(msg)
            members_per_group.append(group.siblings_including_selected)
        for i, scheme_a in enumerate(members_per_group):
            for scheme_b in members_per_group[i + 1 :]:
                overlap = scheme_a & scheme_b
                if overlap:
                    msg = (
                        "Two concept filters resolve to the same scheme. Overlap: "
                        f"{sorted(overlap)}"
                    )
                    raise SiblingGroupingError(msg)
        return tuple(groups)
