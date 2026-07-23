"""Repositories for references and associated models."""

import datetime
from abc import ABC
from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any, ClassVar, Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import AsyncSearch, Q
from elasticsearch.dsl.query import Bool, MatchAll, Prefix, Query, Range, Term, Terms
from elasticsearch.dsl.response import Response
from opentelemetry import trace
from sqlalchemy import (
    CompoundSelect,
    Select,
    and_,
    func,
    intersect_all,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.telemetry.repository import (
    trace_repository_generator,
    trace_repository_method,
)
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.domain.references.models.models import (
    AnnotationFilter,
    CandidateCanonicalSearchQuery,
    CrossFacetAxis,
    CrossFacetCell,
    DuplicateDetermination,
    FacetType,
    GenericExternalIdentifier,
    LinkedDataConceptFilter,
    LinkedDataCountryFilter,
    LinkedDataCountryWBRegionFilter,
    PendingEnhancementStatus,
    PublicationYearRange,
    ReferenceSearchProjection,
    ReferenceWithChangeset,
    RobotAutomationPercolationResult,
    SearchQuery,
    SiblingGroup,
)
from app.domain.references.models.models import (
    Enhancement as DomainEnhancement,
)
from app.domain.references.models.models import (
    EnhancementRequest as DomainEnhancementRequest,
)
from app.domain.references.models.models import (
    LinkedExternalIdentifier as DomainExternalIdentifier,
)
from app.domain.references.models.models import (
    PendingEnhancement as DomainPendingEnhancement,
)
from app.domain.references.models.models import (
    Reference as DomainReference,
)
from app.domain.references.models.models import (
    ReferenceDuplicateDecision as DomainReferenceDuplicateDecision,
)
from app.domain.references.models.models import (
    ReferenceExport as DomainReferenceExport,
)
from app.domain.references.models.models import (
    RobotAutomation as DomainRobotAutomation,
)
from app.domain.references.models.models import (
    RobotEnhancementBatch as DomainRobotEnhancementBatch,
)
from app.domain.references.models.models import (
    SearchExport as DomainSearchExport,
)
from app.domain.references.models.projections import (
    EnhancementRequestStatusProjection,
)
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    EnhancementRequest as SQLEnhancementRequest,
)
from app.domain.references.models.sql import ExternalIdentifier as SQLExternalIdentifier
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.models.sql import (
    ReferenceDuplicateDecision as SQLReferenceDuplicateDecision,
)
from app.domain.references.models.sql import (
    ReferenceExport as SQLReferenceExport,
)
from app.domain.references.models.sql import RobotAutomation as SQLRobotAutomation
from app.domain.references.models.sql import (
    RobotEnhancementBatch as SQLRobotEnhancementBatch,
)
from app.domain.references.models.sql import SearchExport as SQLSearchExport
from app.persistence.es.index_manager import IndexManager
from app.persistence.es.persistence import (
    CandidateCanonicalSearchResult,
    ESFacetBucket,
    ESScoreResult,
    ESSearchResult,
    ESSearchTotal,
)
from app.persistence.es.repository import GenericAsyncESRepository
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository

settings = get_settings()
tracer = trace.get_tracer(__name__)


class ReferenceRepositoryBase(
    GenericAsyncRepository[DomainReference, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for References."""


_reference_sql_preloadable = Literal[
    "identifiers",
    "enhancements",
    "duplicate_references",
    "canonical_reference",
    "duplicate_decision",
]


class ReferenceSQLRepository(
    GenericAsyncSqlRepository[
        DomainReference, SQLReference, _reference_sql_preloadable
    ],
    ReferenceRepositoryBase,
):
    """Concrete implementation of a repository for references using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainReference,
            SQLReference,
        )

    @trace_repository_method(tracer)
    async def get_hydrated(
        self,
        reference_ids: list[UUID],
        enhancement_types: list[str] | None = None,
        external_identifier_types: list[str] | None = None,
    ) -> list[DomainReference]:
        """
        Get a list of references with enhancements and identifiers by id.

        If enhancement_types or external_identifier_types are provided,
        only those types will be included in the results. Otherwise all
        enhancements and identifiers will be included.
        """
        query = select(SQLReference).where(SQLReference.id.in_(reference_ids))
        if enhancement_types:
            query = query.options(
                selectinload(
                    SQLReference.enhancements.and_(
                        SQLEnhancement.enhancement_type.in_(enhancement_types)
                    )
                )
            )
        else:
            query = query.options(selectinload(SQLReference.enhancements))
        if external_identifier_types:
            query = query.options(
                selectinload(
                    SQLReference.identifiers.and_(
                        SQLExternalIdentifier.identifier_type.in_(
                            external_identifier_types
                        )
                    )
                )
            )
        else:
            query = query.options(selectinload(SQLReference.identifiers))
        result = await self._session.execute(query)
        db_references = result.unique().scalars().all()
        return [
            db_reference.to_domain(preload=["enhancements", "identifiers"])
            for db_reference in db_references
        ]

    @trace_repository_method(tracer)
    async def find_with_identifiers(
        self,
        identifiers: Sequence[GenericExternalIdentifier],
        preload: list[_reference_sql_preloadable] | None = None,
        match: Literal["all", "any"] = "all",
    ) -> list[DomainReference]:
        """
        Find references that possess ALL or ANY of the given identifiers.

        :param identifiers: List of external identifiers to match against.
        :type identifiers: list[GenericExternalIdentifier]
        :param preload: List of relationships to preload.
        :type preload: list[_reference_sql_preloadable] | None
        :param match: Whether to match 'all' or 'any' of the identifiers.
        :type match: Literal["all", "any"]

        Returns:
            List of DomainReference objects matching the criteria.

        """
        if not identifiers:
            return []

        options = []
        if preload:
            options.extend(self._get_relationship_loads(preload))

        predicates = [
            and_(
                SQLExternalIdentifier.identifier_type == identifier.identifier_type,
                SQLExternalIdentifier.identifier == identifier.identifier,
                SQLExternalIdentifier.other_identifier_name
                == identifier.other_identifier_name,
            )
            for identifier in identifiers
        ]

        subquery: CompoundSelect[tuple[UUID]] | Select[tuple[UUID]]
        if match == "any":
            subquery = (
                select(SQLExternalIdentifier.reference_id)
                .where(or_(*predicates))
                .distinct()
            )
        else:
            subquery = intersect_all(
                *[
                    select(SQLExternalIdentifier.reference_id).where(predicate)
                    for predicate in predicates
                ]
            )

        query = (
            select(SQLReference).where(SQLReference.id.in_(subquery)).options(*options)
        )

        result = await self._session.execute(query)
        db_references = result.unique().scalars().all()
        return [
            db_reference.to_domain(preload=preload) for db_reference in db_references
        ]


class ReferenceESRepository(
    GenericAsyncESRepository[ReferenceSearchProjection, ReferenceDocument],
    ReferenceRepositoryBase,
):
    """Concrete implementation of a repository for references using Elasticsearch."""

    default_search_fields: ClassVar[tuple[str, ...]] = (
        "title",
        "abstract",
    )
    """Fields the user-supplied query string searches against by default."""

    _FACET_FIELDS: ClassVar[dict[FacetType, str]] = {
        FacetType.CONCEPTS: "linked_data_concepts",
        FacetType.COUNTRIES: "linked_data_countries",
        FacetType.COUNTRY_WB_REGIONS: "linked_data_country_wb_regions",
    }
    """Mapping from a facet type to the ES field its counts are aggregated on."""

    def __init__(self, client: AsyncElasticsearch) -> None:
        """Initialize the repository with the Elasticsearch client."""
        super().__init__(
            client,
            ReferenceSearchProjection,
            ReferenceDocument,
        )

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

    def _build_linked_data_country_clause(
        self,
        country_filter: LinkedDataCountryFilter,
    ) -> Query:
        """Terms clause matching any of the listed ISO codes (OR semantics)."""
        return Terms(linked_data_countries=country_filter.country_codes)

    def _build_linked_data_country_wb_region_clause(
        self,
        region_filter: LinkedDataCountryWBRegionFilter,
    ) -> Query:
        """Terms clause matching any of the listed WB region IDs (OR semantics)."""
        return Terms(linked_data_country_wb_regions=region_filter.region_ids)

    def _build_annotation_clause(self, annotation: AnnotationFilter) -> Query:
        """
        Build a structured DSL clause for an annotation filter.

        Three cases are handled:
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

    def _build_filter_clauses(
        self, query: SearchQuery, *, exclude_facet: FacetType | None = None
    ) -> list[Query]:
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
        if exclude_facet is not FacetType.CONCEPTS:
            clauses.extend(
                self._build_linked_data_concept_clause(concept_filter)
                for concept_filter in query.linked_data_concept_filters
            )
        if exclude_facet is not FacetType.COUNTRIES:
            clauses.extend(
                self._build_linked_data_country_clause(country_filter)
                for country_filter in query.linked_data_country_filters
            )
        if exclude_facet is not FacetType.COUNTRY_WB_REGIONS:
            clauses.extend(
                self._build_linked_data_country_wb_region_clause(region_filter)
                for region_filter in query.linked_data_country_wb_region_filters
            )
        return clauses

    @trace_repository_method(tracer)
    async def search(
        self,
        query: SearchQuery,
        page: int = 1,
        page_size: int = 20,
        sort: list[str] | None = None,
    ) -> ESSearchResult:
        """Search references matching ``query``; structured filters AND with q."""
        # Append the unique doc id as a final tie-breaker so equal-sort-value hits
        # have a deterministic order. unmapped_type allows it to work prior to the
        # migration that adds the id field, this can optionally be removed later
        tiebreaker: dict[str, Any] = {
            "id": {"order": "desc", "unmapped_type": "keyword"}
        }
        return await self.search_with_query_string(
            query.query_string,
            fields=self.default_search_fields,
            page=page,
            page_size=page_size,
            sort=[*sort, tiebreaker] if sort else ["_score", tiebreaker],
            filter_clauses=self._build_filter_clauses(query),
            parse_document=False,
        )

    @trace_repository_generator(tracer)
    async def scan(
        self,
        query: SearchQuery,
        sort: list[str] | None = None,
        limit: int | None = None,
        page_size: int = 500,
    ) -> AsyncGenerator[ESSearchResult, None]:
        """
        Scan references matching ``query`` in pages.

        ``scan_with_query_string`` appends the ``id`` tiebreaker, so unlike
        :meth:`search` this method doesn't add one itself.
        """
        sort_keys: list[str | dict[str, Any]] = list(sort) if sort else ["_score"]
        async for page in self.scan_with_query_string(
            query.query_string,
            fields=self.default_search_fields,
            limit=limit,
            page_size=page_size,
            sort=sort_keys,
            filter_clauses=self._build_filter_clauses(query),
            parse_document=False,
        ):
            yield page

    @trace_repository_method(tracer)
    async def aggregate_facets(
        self,
        query: SearchQuery,
        facets: Sequence[FacetType],
        *,
        sibling_groups_by_facet: Mapping[FacetType, Sequence[SiblingGroup]]
        | None = None,
        max_buckets: int,
    ) -> dict[FacetType, list[ESFacetBucket]]:
        """
        Count occurrences per facet over references matching ``query``.

        For simplicity, constructs and executes different queries per facet type. If
        we're hunting down performance gains later, consider constructing a single
        query - it won't be easy though.
        """
        sibling_groups_by_facet = sibling_groups_by_facet or {}
        results: dict[FacetType, list[ESFacetBucket]] = {}

        ungrouped_facets = [f for f in facets if not sibling_groups_by_facet.get(f)]
        if ungrouped_facets:
            # Simple aggregation for facets without sibling groups
            facet_to_field = {f: self._FACET_FIELDS[f] for f in ungrouped_facets}
            buckets_by_field = await self.aggregate_terms(
                query.query_string,
                aggregate_on=list(facet_to_field.values()),
                query_fields=self.default_search_fields,
                filter_clauses=self._build_filter_clauses(query),
                max_buckets=max_buckets,
            )
            results.update(
                {f: buckets_by_field[field] for f, field in facet_to_field.items()}
            )

        for facet in facets:
            groups = sibling_groups_by_facet.get(facet)
            if not groups:
                continue
            results[facet] = await self._aggregate_facet_sibling_aware(
                query, facet, groups, max_buckets=max_buckets
            )

        return results

    async def _aggregate_facet_sibling_aware(
        self,
        query: SearchQuery,
        facet: FacetType,
        groups: Sequence[SiblingGroup],
        *,
        max_buckets: int,
    ) -> list[ESFacetBucket]:
        """
        Run sibling-aware aggregation for one facet.

        Each group's selection becomes a Terms clause. Aggs are wrapped in
        ``filter`` aggs that AND in the *other* groups' selections — OR within
        a group (multi-URI Terms); AND between groups.
        """
        field = self._FACET_FIELDS[facet]
        group_clauses = [Terms(**{field: list(g.selected)}) for g in groups]

        # Build search query excluding the facet's own filter so its agg
        # includes sibling counts
        search = self._build_aggregation_search(
            query.query_string,
            self.default_search_fields,
            self._build_filter_clauses(query, exclude_facet=facet),
        )

        # Attach aggregate groupings
        agg_names = self._attach_per_group_aggs(
            search, field, groups, group_clauses, max_buckets=max_buckets
        )
        # Universal-mode groups cover the whole field domain, so the "unselected"
        # bucket is empty - skip the agg in that case.
        if all(g.siblings_including_selected is not None for g in groups):
            agg_names.append(
                self._attach_unselected_agg(
                    search, field, groups, group_clauses, max_buckets=max_buckets
                )
            )

        response = await self._execute_search(search)

        return self._parse_facet_buckets(response, agg_names)

    @staticmethod
    def _attach_per_group_aggs(
        search: AsyncSearch,
        field: str,
        groups: Sequence[SiblingGroup],
        group_clauses: Sequence[Query],
        *,
        max_buckets: int,
    ) -> list[str]:
        """Attach one filter+terms agg per group to count each group's sibling set."""
        names: list[str] = []
        for i, group in enumerate(groups):
            other_clauses = [c for j, c in enumerate(group_clauses) if j != i]
            siblings = group.siblings_including_selected
            name = f"facet_group_{i}"
            outer = search.aggs.bucket(
                name,
                "filter",
                filter=Bool(filter=other_clauses) if other_clauses else MatchAll(),
            )
            if siblings is None:
                outer.bucket(
                    "inner",
                    "terms",
                    field=field,
                    min_doc_count=0,
                    size=max_buckets,
                )
            else:
                outer.bucket(
                    "inner",
                    "terms",
                    field=field,
                    min_doc_count=0,
                    size=len(siblings),
                    include=sorted(siblings),
                )
            names.append(name)
        return names

    @staticmethod
    def _attach_unselected_agg(
        search: AsyncSearch,
        field: str,
        groups: Sequence[SiblingGroup],
        group_clauses: Sequence[Query],
        *,
        max_buckets: int,
    ) -> str:
        """Attach the ``unselected`` agg: field values outside any group's siblings."""
        sibling_sets: list[frozenset[str]] = []
        for g in groups:
            if g.siblings_including_selected is None:
                msg = "_attach_unselected_agg requires enumerated sibling groups."
                raise ValueError(msg)
            sibling_sets.append(g.siblings_including_selected)
        all_grouped_uris: frozenset[str] = frozenset().union(*sibling_sets)
        outer = search.aggs.bucket(
            "unselected", "filter", filter=Bool(filter=list(group_clauses))
        )
        outer.bucket(
            "inner",
            "terms",
            field=field,
            exclude=sorted(all_grouped_uris),
            min_doc_count=1,
            size=max_buckets,
        )
        return "unselected"

    @staticmethod
    def _parse_facet_buckets(
        response: Response, agg_names: Sequence[str]
    ) -> list[ESFacetBucket]:
        """Flatten ``filter > terms`` buckets across ``agg_names`` into one list."""
        return [
            ESFacetBucket(key=str(b.key), count=b.doc_count)
            for name in agg_names
            for b in response.aggregations[name].inner.buckets
        ]

    @trace_repository_method(tracer)
    async def aggregate_cross_facet(
        self,
        query: SearchQuery,
        axes: Sequence[CrossFacetAxis],
    ) -> tuple[list[CrossFacetCell], ESSearchTotal]:
        """
        Cross-tabulate two axes over references matching ``query``.

        Returns the non-zero cells plus the exact grand total (``track_total_hits`` is
        enabled so the count isn't capped at the result window).
        """
        axis_0, axis_1 = axes
        search = self._build_aggregation_search(
            query.query_string,
            self.default_search_fields,
            self._build_filter_clauses(query),
        ).extra(track_total_hits=True)
        outer = search.aggs.bucket("axis_0", "terms", **self._facet_agg_params(axis_0))
        outer.bucket("axis_1", "terms", **self._facet_agg_params(axis_1))

        response = await self._execute_search(search)
        return (
            self._parse_cross_facet_cells(response),
            ESSearchTotal(
                value=response.hits.total.value,  # type: ignore[attr-defined]
                relation=response.hits.total.relation,  # type: ignore[attr-defined]
            ),
        )

    def _facet_agg_params(self, axis: CrossFacetAxis) -> dict[str, object]:
        """``terms`` agg params for an axis: field, size, and (for schemes) include."""
        params: dict[str, object] = {
            "field": self._FACET_FIELDS[axis.facet_type],
            "size": axis.size,
        }
        if axis.include:
            params["include"] = sorted(axis.include)
        return params

    @staticmethod
    def _parse_cross_facet_cells(response: Response) -> list[CrossFacetCell]:
        """Flatten nested ``axis_0 > axis_1`` buckets into deterministic cells."""
        cells = [
            CrossFacetCell(
                axes=(str(bucket_0.key), str(bucket_1.key)),
                count=bucket_1.doc_count,
            )
            for bucket_0 in response.aggregations.axis_0.buckets
            for bucket_1 in bucket_0.axis_1.buckets
        ]
        cells.sort(key=lambda cell: (-cell.count, cell.axes))
        return cells

    @staticmethod
    def _to_es_candidate_query(query: CandidateCanonicalSearchQuery) -> Q:
        """Translate a domain candidate query into Elasticsearch DSL."""
        # bool.should sums every matching author clause, so large collaborations can
        # drown out title relevance. dis_max bounds that contribution around the best
        # author match while its tie-breaker gives smaller credit to additional ones.
        author_query = (
            Q(
                "dis_max",
                queries=[Q("match", authors=terms) for terms in query.author_terms],
                tie_breaker=query.author_tie_breaker,
            )
            if query.author_terms
            else None
        )
        should_clauses = [author_query] if author_query else []
        filter_clauses = []
        if query.publication_year_range is not None:
            start, end = query.publication_year_range
            filter_clauses.append(
                Q("range", publication_year={"gte": start, "lte": end})
            )
        filter_clauses.append(
            Q(
                "term",
                duplicate_determination=query.duplicate_determination,
            )
        )
        return Q(
            "bool",
            must=[
                Q(
                    "match",
                    title={
                        "query": query.title,
                        "fuzziness": query.title_fuzziness,
                        "boost": query.title_boost,
                        "operator": query.title_operator,
                        "minimum_should_match": query.title_minimum_should_match,
                    },
                )
            ],
            should=should_clauses,
            filter=filter_clauses,
            must_not=[Q("ids", values=[query.excluded_reference_id])]
            if query.excluded_reference_id
            else [],
        )

    @trace_repository_method(tracer)
    async def search_for_candidate_canonicals(
        self,
        query: CandidateCanonicalSearchQuery,
        *,
        k: int,
        track_total_hits: bool = False,
    ) -> CandidateCanonicalSearchResult:
        """
        Execute a candidate-canonical search specification in Elasticsearch.

        The deduplication service owns retrieval-policy interpretation and query
        semantics; this repository translates the resulting specification into
        Elasticsearch DSL and executes it.

        :param query: The domain search specification to execute.
        :type query: CandidateCanonicalSearchQuery
        :param k: Maximum number of candidates to return.
        :type k: int
        :param track_total_hits: Compute the exact total hit count instead of the
            Elasticsearch default (capped at 10k). Off by default so the nomination
            path, which ignores the total, does not pay for a full count.
        :type track_total_hits: bool
        :return: Ranked candidate ids with scores and retrieval diagnostics.
        :rtype: CandidateCanonicalSearchResult
        """
        search = (
            AsyncSearch(using=self._client, index=self._persistence_cls.Index.name)
            .query(self._to_es_candidate_query(query))
            .source(fields=False)
            .extra(size=k)
        )
        # Only force an exact count when asked; leaving it unset keeps the ES default
        # (accurate up to 10k, then a lower bound) rather than disabling totals.
        if track_total_hits:
            search = search.extra(track_total_hits=True)

        response = await search.execute()

        hits = sorted(
            [
                ESScoreResult(id=hit.meta.id, score=hit.meta.score)
                for hit in response.hits
            ],
            key=lambda result: result.score,
            reverse=True,
        )
        return CandidateCanonicalSearchResult(
            hits=hits,
            # ES DSL typing on response.hits is incorrect
            total=ESSearchTotal(
                value=response.hits.total.value,  # type: ignore[attr-defined]
                relation=response.hits.total.relation,  # type: ignore[attr-defined]
            ),
            took_ms=response.took,
        )

    @trace_repository_method(tracer)
    async def get_current_index_name(self) -> str | None:
        """Return the physical index name currently behind the alias, if any."""
        return await IndexManager(
            self._persistence_cls, self._client
        ).get_current_index_name()


class ExternalIdentifierRepositoryBase(
    GenericAsyncRepository[DomainExternalIdentifier, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for external identifiers."""


_external_identifier_sql_preloadable = Literal["reference"]


class ExternalIdentifierSQLRepository(
    GenericAsyncSqlRepository[
        DomainExternalIdentifier,
        SQLExternalIdentifier,
        _external_identifier_sql_preloadable,
    ],
    ExternalIdentifierRepositoryBase,
):
    """Concrete implementation of a repository for identifiers using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainExternalIdentifier,
            SQLExternalIdentifier,
        )


class EnhancementRepositoryBase(
    GenericAsyncRepository[DomainEnhancement, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for external identifiers."""


class EnhancementSQLRepository(
    GenericAsyncSqlRepository[DomainEnhancement, SQLEnhancement, Literal["reference"]],
    EnhancementRepositoryBase,
):
    """Concrete implementation of a repository for identifiers using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainEnhancement,
            SQLEnhancement,
        )


class EnhancementRequestRepositoryBase(
    GenericAsyncRepository[DomainEnhancementRequest, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for batch enhancement requests."""


EnhancementRequestSQLPreloadable = Literal["pending_enhancements", "status"]


class EnhancementRequestSQLRepository(
    GenericAsyncSqlRepository[
        DomainEnhancementRequest,
        SQLEnhancementRequest,
        EnhancementRequestSQLPreloadable,
    ],
    EnhancementRequestRepositoryBase,
):
    """Concrete implementation of a repository for batch enhancement requests."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainEnhancementRequest,
            SQLEnhancementRequest,
        )

    async def get_pending_enhancement_status_set(
        self, enhancement_request_id: UUID
    ) -> set[PendingEnhancementStatus]:
        """
        Get current underlying statuses for an enhancement request.

        Args:
            enhancement_request_id: The ID of the enhancement request

        Returns:
            Set of statuses for the pending enhancements in the request

        """
        query = select(
            SQLPendingEnhancement.status.distinct(),
        ).where(SQLPendingEnhancement.enhancement_request_id == enhancement_request_id)
        results = await self._session.execute(query)
        return {row[0] for row in results.all()}

    async def get_by_pk(
        self,
        pk: UUID,
        preload: list[EnhancementRequestSQLPreloadable] | None = None,
    ) -> DomainEnhancementRequest:
        """Override to include derived enhancement request status."""
        enhancement_request = await super().get_by_pk(pk, preload)
        if "status" in (preload or []):
            status_set = await self.get_pending_enhancement_status_set(pk)
            return EnhancementRequestStatusProjection.get_from_status_set(
                enhancement_request, status_set
            )
        return enhancement_request


class SearchExportRepositoryBase(
    GenericAsyncRepository[DomainSearchExport, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for search export jobs."""


class SearchExportSQLRepository(
    GenericAsyncSqlRepository[DomainSearchExport, SQLSearchExport, Literal["__none__"]],
    SearchExportRepositoryBase,
):
    """Concrete implementation of a repository for search exports using SQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainSearchExport,
            SQLSearchExport,
        )


class ReferenceExportRepositoryBase(
    GenericAsyncRepository[DomainReferenceExport, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for reference export jobs."""


class ReferenceExportSQLRepository(
    GenericAsyncSqlRepository[
        DomainReferenceExport, SQLReferenceExport, Literal["__none__"]
    ],
    ReferenceExportRepositoryBase,
):
    """Concrete implementation of a repository for reference exports using SQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainReferenceExport,
            SQLReferenceExport,
        )


class RobotAutomationRepositoryBase(
    GenericAsyncRepository[DomainRobotAutomation, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Robot Automations."""


class RobotAutomationSQLRepository(
    GenericAsyncSqlRepository[
        DomainRobotAutomation, SQLRobotAutomation, Literal["__none__"]
    ],
    RobotAutomationRepositoryBase,
):
    """Concrete implementation of a repository for robot automations using SQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainRobotAutomation,
            SQLRobotAutomation,
        )


class RobotAutomationESRepository(
    GenericAsyncESRepository[DomainRobotAutomation, RobotAutomationPercolationDocument],
    RobotAutomationRepositoryBase,
):
    """Concrete implementation for robot automations using Elasticsearch."""

    def __init__(self, client: AsyncElasticsearch) -> None:
        """Initialize the repository with the Elasticsearch client."""
        super().__init__(
            client,
            DomainRobotAutomation,
            RobotAutomationPercolationDocument,
        )

    @trace_repository_method(tracer)
    async def percolate(
        self,
        percolatables: Sequence[ReferenceWithChangeset],
    ) -> list[RobotAutomationPercolationResult]:
        """
        Percolate documents against the percolation queries in Elasticsearch.

        :param percolatables: A list of percolatable domain objects.
        :type percolatables: list[ReferenceWithChangeset]
        :return: The results of the percolation.
        :rtype: list[RobotAutomationPercolationResult]
        """
        if not settings.feature_flags.enable_percolation:
            return []

        documents = [
            (
                self._persistence_cls.percolatable_document_from_domain(percolatable)
            ).to_dict()
            for percolatable in percolatables
        ]
        results = await (
            self._persistence_cls.search()
            .using(self._client)
            .query(
                {
                    "percolate": {
                        "field": "query",
                        "documents": documents,
                    }
                }
            )
            .execute()
        )

        robot_automation_percolation_results: list[
            RobotAutomationPercolationResult
        ] = []
        for result in results:
            matches: list[ReferenceWithChangeset] = [
                percolatables[slot]
                for slot in result.meta.fields["_percolator_document_slot"]
            ]
            robot_automation_percolation_results.append(
                RobotAutomationPercolationResult(
                    robot_id=result.robot_id,
                    reference_ids={reference.id for reference in matches},
                )
            )

        return robot_automation_percolation_results


class ReferenceDuplicateDecisionRepositoryBase(
    GenericAsyncRepository[DomainReferenceDuplicateDecision, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Reference Duplicate Decisions."""


class ReferenceDuplicateDecisionSQLRepository(
    GenericAsyncSqlRepository[
        DomainReferenceDuplicateDecision,
        SQLReferenceDuplicateDecision,
        Literal["__none__"],
    ],
    ReferenceDuplicateDecisionRepositoryBase,
):
    """Concrete implementation of a repo for Reference Duplicate Decisions using SQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainReferenceDuplicateDecision,
            SQLReferenceDuplicateDecision,
        )

    async def get_active_decision_determinations(
        self, reference_ids: set[UUID]
    ) -> dict[UUID, DuplicateDetermination]:
        """
        Return active decision determinations for a set of references.

        Uses a scalar query to bypass the ORM identity map, ensuring we see
        the latest committed state from other transactions under READ COMMITTED.

        Returns a dict mapping reference_id -> determination for references
        that have an active decision. References without an active decision
        are omitted from the result.
        """
        if not reference_ids:
            return {}
        result = await self._session.execute(
            select(
                SQLReferenceDuplicateDecision.reference_id,
                SQLReferenceDuplicateDecision.duplicate_determination,
            ).where(
                SQLReferenceDuplicateDecision.reference_id.in_(reference_ids),
                SQLReferenceDuplicateDecision.active_decision.is_(True),
            )
        )
        return dict(result.all())


class PendingEnhancementRepositoryBase(
    GenericAsyncRepository[DomainPendingEnhancement, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Pending Enhancements."""


class PendingEnhancementSQLRepository(
    GenericAsyncSqlRepository[
        DomainPendingEnhancement, SQLPendingEnhancement, Literal["__none__"]
    ],
    PendingEnhancementRepositoryBase,
):
    """Concrete implementation of a repository for pending enhancements using SQLAlchemy."""  # noqa: E501

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainPendingEnhancement,
            SQLPendingEnhancement,
        )

    @trace_repository_method(tracer)
    async def update_by_pk(
        self, pk: UUID, **kwargs: object
    ) -> DomainPendingEnhancement:
        """
        Update a pending enhancement by primary key with status validation.

        Overrides the base implementation to validate status transitions
        before performing the update.

        Args:
            pk: Primary key of the pending enhancement to update
            kwargs: Fields to update (including optional 'status')

        Returns:
            The updated pending enhancement

        Raises:
            StateTransitionError: If any status transition is invalid

        """
        if "status" in kwargs:
            new_status = PendingEnhancementStatus(kwargs["status"])  # type: ignore[arg-type]
            current_entity = await self.get_by_pk(pk)
            current_entity.status.guard_transition(new_status, pk)

        return await super().update_by_pk(pk, **kwargs)

    @trace_repository_method(tracer)
    async def bulk_update(self, pks: list[UUID], **kwargs: object) -> int:
        """
        Bulk update pending enhancements with status transition validation.

        Overrides the base implementation to validate status transitions
        before performing the update.

        Args:
            pks: List of pending enhancement IDs to update
            kwargs: Fields to update (including optional 'status')

        Returns:
            Number of records updated

        Raises:
            ValueError: If any status transition is invalid

        """
        if "status" in kwargs and pks:
            new_status = PendingEnhancementStatus(kwargs["status"])  # type: ignore[arg-type]

            stmt = select(SQLPendingEnhancement.id, SQLPendingEnhancement.status).where(
                SQLPendingEnhancement.id.in_(pks)
            )
            result = await self._session.execute(stmt)
            entities = result.all()

            for entity_id, current_status_value in entities:
                current_status = PendingEnhancementStatus(current_status_value)
                current_status.guard_transition(new_status, entity_id)

        return await super().bulk_update(pks, **kwargs)

    @trace_repository_method(tracer)
    async def bulk_update_by_filter(
        self, filter_conditions: dict[str, object], **kwargs: object
    ) -> int:
        """
        Bulk update pending enhancements by filter with status validation.

        Overrides the base implementation to validate status transitions
        before performing the update.

        Args:
            filter_conditions: Conditions to filter records
            kwargs: Fields to update (including optional 'status')

        Returns:
            Number of records updated

        Raises:
            ValueError: If any status transition is invalid

        """
        if "status" in kwargs:
            new_status = PendingEnhancementStatus(kwargs["status"])  # type: ignore[arg-type]

            entities = await self.find(
                order_by=None, limit=None, preload=None, **filter_conditions
            )

            for entity in entities:
                entity.status.guard_transition(new_status, entity.id)

        return await super().bulk_update_by_filter(filter_conditions, **kwargs)

    @trace_repository_method(tracer)
    async def find_available_for_robot(
        self,
        robot_id: UUID,
        limit: int,
    ) -> list[DomainPendingEnhancement]:
        """
        Find pending enhancements available for a robot, locking rows.

        Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent concurrent robot
        replicas from claiming the same pending enhancements.
        """
        query = (
            select(SQLPendingEnhancement)
            .where(
                SQLPendingEnhancement.robot_id == robot_id,
                SQLPendingEnhancement.robot_enhancement_batch_id.is_(None),
                SQLPendingEnhancement.status == PendingEnhancementStatus.PENDING,
            )
            .order_by(SQLPendingEnhancement.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        result = await self._session.execute(query)
        return [record.to_domain() for record in result.scalars().all()]

    @trace_repository_method(tracer)
    async def count_retry_depth(self, pending_enhancement_id: UUID) -> int:
        """
        Count how many times a pending enhancement has been retried.

        This recursively follows the retry_of chain to count the depth.

        Args:
            pending_enhancement_id: ID of the pending enhancement to check

        Returns:
            Number of retries (0 if this is the original)

        """
        # Use a recursive CTE to count retry depth
        cte = (
            select(
                SQLPendingEnhancement.id,
                SQLPendingEnhancement.retry_of,
                literal(0).label("depth"),
            )
            .where(SQLPendingEnhancement.id == pending_enhancement_id)
            .cte(name="retry_chain", recursive=True)
        )

        # Recursive part: join to find the parent (retry_of)
        recursive_part = select(
            SQLPendingEnhancement.id,
            SQLPendingEnhancement.retry_of,
            (cte.c.depth + 1).label("depth"),
        ).join(
            SQLPendingEnhancement,
            SQLPendingEnhancement.id == cte.c.retry_of,
        )

        cte = cte.union_all(recursive_part)

        # Get the maximum depth
        query = select(func.max(cte.c.depth))
        result = await self._session.execute(query)
        depth = result.scalar()

        return depth if depth is not None else 0

    @trace_repository_method(tracer)
    async def expire_pending_enhancements_past_expiry(
        self,
        now: datetime.datetime,
        statuses: list[PendingEnhancementStatus],
    ) -> list[DomainPendingEnhancement]:
        """
        Atomically find and expire pending enhancements past their expiry time.

        This method updates the status to EXPIRED and returns the expired records
        in a single atomic operation to prevent race conditions in parallel execution.

        Args:
            now: Current datetime to compare against expires_at
            statuses: List of statuses to filter by (e.g., PROCESSING)

        Returns:
            List of pending enhancements that were expired

        """
        stmt = (
            update(SQLPendingEnhancement)
            .where(
                SQLPendingEnhancement.expires_at < now,
                SQLPendingEnhancement.status.in_([status.value for status in statuses]),
            )
            .values(status=PendingEnhancementStatus.EXPIRED.value)
            .returning(SQLPendingEnhancement)
        )

        result = await self._session.execute(stmt)
        return [record.to_domain() for record in result.scalars().all()]


class RobotEnhancementBatchRepositoryBase(
    GenericAsyncRepository[DomainRobotEnhancementBatch, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Robot Enhancement Batches."""


RobotEnhancementBatchSQLPreloadable = Literal["pending_enhancements"]


class RobotEnhancementBatchSQLRepository(
    GenericAsyncSqlRepository[
        DomainRobotEnhancementBatch,
        SQLRobotEnhancementBatch,
        RobotEnhancementBatchSQLPreloadable,
    ],
    RobotEnhancementBatchRepositoryBase,
):
    """Concrete implementation of a repository for robot enhancement batches using SQLAlchemy."""  # noqa: E501

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainRobotEnhancementBatch,
            SQLRobotEnhancementBatch,
        )
