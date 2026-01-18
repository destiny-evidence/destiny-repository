"""Repositories for references and associated models."""

import datetime
import math
import re
from abc import ABC
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import AsyncSearch, Q
from opentelemetry import trace
from pydantic import UUID4
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
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.telemetry.repository import trace_repository_method
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
    DuplicateDetermination,
    GenericExternalIdentifier,
    PendingEnhancementStatus,
    ReferenceWithChangeset,
    RobotAutomationPercolationResult,
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
    RobotAutomation as DomainRobotAutomation,
)
from app.domain.references.models.models import (
    RobotEnhancementBatch as DomainRobotEnhancementBatch,
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
from app.domain.references.models.sql import RobotAutomation as SQLRobotAutomation
from app.domain.references.models.sql import (
    RobotEnhancementBatch as SQLRobotEnhancementBatch,
)
from app.persistence.es.persistence import ESScoreResult
from app.persistence.es.repository import GenericAsyncESRepository
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository

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
                joinedload(
                    SQLReference.enhancements.and_(
                        SQLEnhancement.enhancement_type.in_(enhancement_types)
                    )
                )
            )
        else:
            query = query.options(joinedload(SQLReference.enhancements))
        if external_identifier_types:
            query = query.options(
                joinedload(
                    SQLReference.identifiers.and_(
                        SQLExternalIdentifier.identifier_type.in_(
                            external_identifier_types
                        )
                    )
                )
            )
        else:
            query = query.options(joinedload(SQLReference.identifiers))
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


# =============================================================================
# Deduplication Query Helpers
# =============================================================================
#
# These helpers address the "ATLAS/sausages" false positive problem where:
# - An ATLAS physics paper (2927 authors) was matched to a food science paper
# - ES score reached 2780 due to stopword title matches + author initial matching
#
# Solution layers:
# 1. Title matching calculates MSM based on content tokens (excludes stopwords)
# 2. Authors use dis_max (caps contribution to best match, not sum of 2927)
# 3. Collaboration papers (>50 authors) skip individual author matching
# 4. Query-side token filtering for minimum_should_match calculation

_TOKEN_PATTERN = re.compile(r"\b[a-zA-Z]+\b")

# English stopwords (matches ES _english_ stopwords list)
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
    ]
)

# Keywords indicating collaboration/consortium authorship
_COLLABORATION_KEYWORDS = frozenset(
    [
        "collaboration",
        "consortium",
        "group",
        "team",
        "working",
        "project",
    ]
)


def _count_content_tokens(text: str, min_length: int = 3) -> int:
    """
    Count content tokens (excluding stopwords and short tokens).

    Used to compute minimum_should_match for title field queries.

    Args:
        text: Text to tokenize.
        min_length: Minimum token length (default 3, matching ES analyzer).

    Returns:
        Number of content tokens.

    Example:
        >>> _count_content_tokens("A continuous calibration of the ATLAS")
        3  # ["continuous", "calibration", "atlas"]

    """
    tokens = _TOKEN_PATTERN.findall(text.lower())
    return sum(1 for t in tokens if len(t) >= min_length and t not in _STOPWORDS)


def _is_collaboration_paper(authors: list[str], threshold: int = 50) -> bool:
    """
    Detect if paper is from a large collaboration (ATLAS, CMS, etc.).

    For collaboration papers, individual author matching is skipped because:
    - Authors are not discriminative (2927 authors won't help find duplicates)
    - Single-letter initials cause massive false positive scores

    Args:
        authors: List of author names.
        threshold: Author count threshold (default 50).

    Returns:
        True if paper appears to be from a collaboration.

    """
    if len(authors) > threshold:
        return True
    # Check first few authors for collaboration keywords
    for author in authors[:5]:
        author_lower = author.lower()
        if any(kw in author_lower for kw in _COLLABORATION_KEYWORDS):
            return True
    return False


def _build_author_dis_max_query(
    authors: list[str],
    max_clauses: int,
    min_token_length: int,
    tie_breaker: float = 0.1,
) -> "Q | None":
    """
    Build dis_max query for author matching with bounded contribution.

    Unlike bool.should (which sums all matching clauses), dis_max takes
    the max score + tie_breaker * sum(other scores). This prevents
    2927 author clauses from exploding into a 2780 score.

    Args:
        authors: List of author names.
        max_clauses: Maximum number of match queries to create.
        min_token_length: Minimum token length (filters single-letter initials).
        tie_breaker: dis_max tie_breaker (0.0-1.0, default 0.1).

    Returns:
        dis_max Q object, or None if no valid author queries.

    Example:
        With tie_breaker=0.1 and 3 matching authors scoring [10, 8, 5]:
        - bool.should score: 10 + 8 + 5 = 23
        - dis_max score: 10 + 0.1*(8 + 5) = 11.3

    """
    # Skip collaboration papers entirely
    if _is_collaboration_paper(authors):
        return None

    queries = []
    for author in authors[:max_clauses]:
        # Extract tokens, filtering single-letter initials
        tokens = _TOKEN_PATTERN.findall(author)
        meaningful_tokens = [t for t in tokens if len(t) >= min_token_length]
        if meaningful_tokens:
            # Query the authors.dedup subfield (has analyzer that filters initials)
            query_str = " ".join(meaningful_tokens)
            queries.append(Q("match", **{"authors.dedup": query_str}))

    if not queries:
        return None

    return Q("dis_max", queries=queries, tie_breaker=tie_breaker)


class ReferenceESRepository(
    GenericAsyncESRepository[DomainReference, ReferenceDocument],
    ReferenceRepositoryBase,
):
    """Concrete implementation of a repository for references using Elasticsearch."""

    def __init__(self, client: AsyncElasticsearch) -> None:
        """Initialize the repository with the Elasticsearch client."""
        super().__init__(
            client,
            DomainReference,
            ReferenceDocument,
        )

    @trace_repository_method(tracer)
    async def search_for_candidate_canonicals(
        self,
        search_fields: CandidateCanonicalSearchFields,
        reference_id: UUID,
    ) -> list[ESScoreResult]:
        """
        Fuzzy match candidate fingerprints to existing references.

        This is a high-recall search strategy using a two-pass approach:

        **Pass 1 (Strict):**
        - MUST: fuzzy match on title (requires 50% of terms to match)
        - SHOULD: partial match on authors list (requires 50% of authors to match)
        - FILTER: publication year within ±1 year range (non-scoring)
        - FILTER: Only canonical references (at rest)

        **Pass 2 (Relaxed) - only if Pass 1 returns no results:**
        - MUST: fuzzy match on title (requires 30% of terms to match)
        - SHOULD: partial match on authors list (no minimum)
        - FILTER: publication year within ±2 year range OR missing year (optional)
        - FILTER: Only canonical references (at rest)

        This two-pass approach maximizes recall while keeping the strict query
        fast for the common case where year and title match well.

        :param search_fields: The search fields of the potential duplicate.
        :type search_fields: CandidateCanonicalSearchFields
        :param reference_id: The ID of the potential duplicate.
        :type reference_id: UUID
        :return: A list of search results with IDs and scores.
        :rtype: list[ESScoreResult]
        """
        # Pass 1: Strict query
        strict_results = await self._search_candidates_strict(
            search_fields, reference_id
        )
        if strict_results:
            return strict_results

        # Pass 2: Relaxed query (only if strict found nothing)
        return await self._search_candidates_relaxed(search_fields, reference_id)

    async def _search_candidates_strict(
        self,
        search_fields: CandidateCanonicalSearchFields,
        reference_id: UUID,
    ) -> list[ESScoreResult]:
        """
        Execute strict candidate search with tight year filter.

        Uses title field with content-token-based MSM (stopwords excluded from
        count) and dis_max for authors (bounded score contribution).
        """
        settings = get_settings()
        config = settings.dedup_scoring

        # Build year filter only if year is present
        filters = [
            Q("term", duplicate_determination=DuplicateDetermination.CANONICAL),
        ]
        if search_fields.publication_year:
            filters.append(
                Q(
                    "range",
                    publication_year={
                        "gte": search_fields.publication_year - 1,
                        "lte": search_fields.publication_year + 1,
                    },
                )
            )

        # Calculate MSM based on content tokens (excludes stopwords/short tokens)
        # This prevents "a", "of", "the" from satisfying the title match threshold
        title = search_fields.title or ""
        content_token_count = _count_content_tokens(title)
        # Require 50% of content tokens, minimum 2 tokens
        title_msm = max(2, math.floor(0.5 * content_token_count))

        # Build author dis_max query (bounded contribution, no single-letter initials)
        # Returns None for collaboration papers (>50 authors)
        author_query = _build_author_dis_max_query(
            search_fields.authors,
            max_clauses=config.max_author_clauses,
            min_token_length=config.min_author_token_length,
        )

        # Build should clauses - author query contributes to score but isn't required
        should_clauses = [author_query] if author_query else []

        search = (
            AsyncSearch(using=self._client, index=self._persistence_cls.Index.name)
            .query(
                Q(
                    "bool",
                    must=[
                        Q(
                            "match",
                            # Match on title field
                            title={
                                "query": search_fields.title,
                                "fuzziness": "AUTO",
                                "boost": 2.0,
                                "operator": "or",
                                "minimum_should_match": title_msm,
                            },
                        )
                    ],
                    should=should_clauses,
                    filter=filters,
                    must_not=[Q("ids", values=[reference_id])],
                )
            )
            .source(fields=False)
        )

        response = await search.execute()

        return sorted(
            [
                ESScoreResult(id=hit.meta.id, score=hit.meta.score)
                for hit in response.hits
            ],
            key=lambda result: result.score,
            reverse=True,
        )

    async def _search_candidates_relaxed(
        self,
        search_fields: CandidateCanonicalSearchFields,
        reference_id: UUID,
    ) -> list[ESScoreResult]:
        """
        Execute relaxed candidate search with optional year filter.

        Uses title field with content-token-based MSM (stopwords excluded from
        count) and dis_max for authors (bounded score contribution).
        """
        settings = get_settings()
        config = settings.dedup_scoring

        # Relaxed: wider year range OR missing year (should + min_should_match=0)
        # Allows matching records with no year, or year ±2
        filters = [
            Q("term", duplicate_determination=DuplicateDetermination.CANONICAL),
        ]

        # Year is now a SHOULD with wider range, not a hard filter
        year_should_clauses = []
        if search_fields.publication_year:
            year_should_clauses.append(
                Q(
                    "range",
                    publication_year={
                        "gte": search_fields.publication_year - 2,
                        "lte": search_fields.publication_year + 2,
                    },
                )
            )
            # Also allow records with no year (missing year should not exclude)
            year_should_clauses.append(
                Q("bool", must_not=[Q("exists", field="publication_year")])
            )

        # Calculate MSM based on content tokens (excludes stopwords/short tokens)
        # This prevents "a", "of", "the" from satisfying the title match threshold
        title = search_fields.title or ""
        content_token_count = _count_content_tokens(title)
        # Require 30% of content tokens, minimum 1 token (relaxed)
        title_msm = max(1, math.floor(0.3 * content_token_count))

        # Build author dis_max query (bounded contribution, no single-letter initials)
        # Returns None for collaboration papers (>50 authors)
        author_query = _build_author_dis_max_query(
            search_fields.authors,
            max_clauses=config.max_author_clauses,
            min_token_length=config.min_author_token_length,
        )

        # Build should clauses - author and year contribute to score but aren't required
        should_clauses = year_should_clauses[:]
        if author_query:
            should_clauses.append(author_query)

        search = (
            AsyncSearch(using=self._client, index=self._persistence_cls.Index.name)
            .query(
                Q(
                    "bool",
                    must=[
                        Q(
                            "match",
                            # Match on title field
                            title={
                                "query": search_fields.title,
                                "fuzziness": "AUTO",
                                "boost": 2.0,
                                "operator": "or",
                                "minimum_should_match": title_msm,
                            },
                        )
                    ],
                    should=should_clauses,
                    filter=filters,
                    must_not=[Q("ids", values=[reference_id])],
                )
            )
            .source(fields=False)
        )

        response = await search.execute()

        return sorted(
            [
                ESScoreResult(id=hit.meta.id, score=hit.meta.score)
                for hit in response.hits
            ],
            key=lambda result: result.score,
            reverse=True,
        )


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
        self, enhancement_request_id: UUID4
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
        pk: UUID4,
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
    async def bulk_update(self, pks: list[UUID4], **kwargs: object) -> int:
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
