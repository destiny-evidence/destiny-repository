"""Repositories for references and associated models."""

import math
from abc import ABC
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import AsyncSearch, Q
from opentelemetry import trace
from pydantic import UUID4
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
from app.persistence.es.persistence import ESSearchResult
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
            SQLReference.identifiers.any(
                and_(
                    SQLExternalIdentifier.identifier_type == identifier.identifier_type,
                    SQLExternalIdentifier.identifier == identifier.identifier,
                    SQLExternalIdentifier.other_identifier_name
                    == identifier.other_identifier_name,
                )
            )
            for identifier in identifiers
        ]

        query = (
            select(SQLReference)
            .where(and_(*predicates) if match == "all" else or_(*predicates))
            .options(*options)
        )

        result = await self._session.execute(query)
        db_references = result.unique().scalars().all()
        return [
            db_reference.to_domain(preload=preload) for db_reference in db_references
        ]


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
    ) -> list[ESSearchResult]:
        """
        Fuzzy match candidate fingerprints to existing references.

        This is a high-recall search strategy.

        NOT TESTED/EVALUATED. Thrown together as a proof of concept, this must
        be polished and evaluated before use.

        The proof of concept does:

        - MUST: fuzzy match on title (requires 50% of terms to match)
        - SHOULD: partial match on authors list (requires 50% of authors to match)
        - FILTER: publication year within ±1 year range (non-scoring)

        :param search_fields: The search fields of the potential duplicate.
        :type search_fields: CandidateCanonicalSearchFields
        :param reference_id: The ID of the potential duplicate.
        :type reference_id: UUID
        :return: A list of search results with IDs and scores.
        :rtype: list[ESSearchResult]
        """
        search = (
            AsyncSearch(using=self._client)
            .doc_type(self._persistence_cls)
            .query(
                Q(
                    "bool",
                    must=[
                        Q(
                            "match",
                            title={
                                "query": search_fields.title,
                                "fuzziness": "AUTO",
                                "boost": 2.0,
                                "operator": "or",
                                "minimum_should_match": "50%",
                            },
                        )
                    ],
                    should=[
                        Q("match", authors=author) for author in search_fields.authors
                    ],
                    filter=[
                        Q(
                            "range",
                            publication_year={
                                "gte": search_fields.publication_year - 1,
                                "lte": search_fields.publication_year + 1,
                            },
                        ),
                        # This filter ensures we only match against references that are
                        # "at rest". This avoids race conditions where reference B and C
                        # are being deduplicated at the same time, perhaps creating
                        # links B->A and C->B - in turn, creating a chain that we do
                        # not control, which is a no-no.
                        # Better handling will be needed in the future if/when we fully
                        # implement chaining (which will require deliberate candidate
                        # selection against duplicates as well as canonicals, probably
                        # still "at rest" though).
                        Q(
                            "term",
                            duplicate_determination=DuplicateDetermination.CANONICAL,
                        ),
                    ]
                    if search_fields.publication_year
                    else [],
                    must_not=[Q("ids", values=[reference_id])],
                    minimum_should_match=math.floor(0.5 * len(search_fields.authors)),
                )
            )
            .source(fields=False)
        )

        response = await search.execute()

        return sorted(
            [
                ESSearchResult(id=hit.meta.id, score=hit.meta.score)
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
