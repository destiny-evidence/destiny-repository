"""Service to synchronize Reference models between persistence implementations."""

from collections.abc import AsyncGenerator, Iterable
from typing import ClassVar
from uuid import UUID

from opentelemetry.trace import get_tracer

from app.core.config import ESIndexingOperation, get_settings
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import Reference, RobotAutomation
from app.domain.references.models.projections import DeduplicatedReferenceProjection
from app.domain.service import GenericSynchronizer
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.utils.lists import list_chunker

tracer = get_tracer(__name__)
settings = get_settings()
logger = get_logger(__name__)


class ReferenceSynchronizer(GenericSynchronizer[Reference]):
    """Service to synchronize Reference models between persistences."""

    _required_preloads: ClassVar[list] = [
        "identifiers",
        "enhancements",
        "canonical_reference",
        "duplicate_references",
        "duplicate_decision",
    ]

    @tracer.start_as_current_span("Sync Reference SQL->ES")
    async def sql_to_es(self, reference_id: UUID) -> Reference:
        """Synchronize a reference from SQL to Elasticsearch."""
        trace_attribute(Attributes.DB_PK, str(reference_id))
        reference = await self.sql_uow.references.get_by_pk(
            reference_id,
            preload=self._required_preloads,
        )

        if not reference.is_canonical_like and reference.canonical_reference:
            # If definitely a duplicate, we don't index and we update the canonical
            await self.es_uow.references.delete_by_pk(reference.id, fail_hard=False)
            return await self.sql_to_es(reference.canonical_reference.id)

        return await self.es_uow.references.add(
            DeduplicatedReferenceProjection.get_from_reference(reference)
        )

    @tracer.start_as_current_span("Sync Reference Bulk SQL->ES")
    async def bulk_sql_to_es(self, reference_ids: Iterable[UUID]) -> int:
        """
        Synchronize multiple references from SQL to Elasticsearch.

        This does not handle any deletions, purely upserting. Destructive reindexes
        should either be done one-by-one or via a ground-up rebuild of the index.
        """
        ids = list(reference_ids)
        chunk_size = settings.es_indexing_chunk_size_override.get(
            ESIndexingOperation.REFERENCE_IMPORT,
            settings.default_es_indexing_chunk_size,
        )

        logger.info(
            "Indexing references in Elasticsearch",
            n_references=len(ids),
            chunk_size=chunk_size,
        )

        async def reference_generator() -> AsyncGenerator[Reference, None]:
            """Generate references for indexing."""
            for reference_id_chunk in list_chunker(
                ids,
                chunk_size,
            ):
                references = await self.sql_uow.references.get_by_pks(
                    reference_id_chunk,
                    preload=self._required_preloads,
                )
                for reference in references:
                    if reference.is_canonical_like:
                        yield DeduplicatedReferenceProjection.get_from_reference(
                            reference
                        )

        return await self.es_uow.references.add_bulk(reference_generator())


class RobotAutomationSynchronizer(GenericSynchronizer[RobotAutomation]):
    """Service to synchronize RobotAutomation models between persistences."""

    @tracer.start_as_current_span("Sync Robot Automation SQL->ES")
    async def sql_to_es(self, robot_automation_id: UUID) -> RobotAutomation:
        """Synchronize a robot automation from SQL to Elasticsearch."""
        trace_attribute(Attributes.DB_PK, str(robot_automation_id))
        robot_automation = await self.sql_uow.robot_automations.get_by_pk(
            robot_automation_id
        )
        return await self.es_uow.robot_automations.add(robot_automation)


class Synchronizer:
    """Service to synchronize models between persistences."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork, es_uow: AsyncESUnitOfWork) -> None:
        """Initialize the synchronizer service."""
        self.references = ReferenceSynchronizer(sql_uow, es_uow)
        self.robot_automations = RobotAutomationSynchronizer(sql_uow, es_uow)
