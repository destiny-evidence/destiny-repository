"""End-to-end tests for happy path imports."""

from collections.abc import Callable
from contextlib import _AsyncGeneratorContextManager
from uuid import UUID

import httpx
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    DuplicateDetermination,
    PendingEnhancementStatus,
)
from tests.e2e.utils import (
    poll_batch_status,
    poll_duplicate_process,
    poll_pending_enhancement,
    refresh_reference_index,
    submit_happy_import_batch,
)


async def test_happy_import(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    generate_sdk_reference_file_inputs: Callable[[int], list[ReferenceFileInput]],
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    robot_automation_on_all_imports: UUID,
):
    """
    Test a simple import of references.

    Checks:
    - All references are successfully imported
    - Deduplication decisions are made
    - Pending enhancements are created for the imported references
        (based on always-passing automation)
    - References are present in all persistence implementations
    """
    n_refs = 10
    async with get_import_file_signed_url(
        generate_sdk_reference_file_inputs(n_refs)
    ) as storage_url:
        import_record_id, import_batch_id = await submit_happy_import_batch(
            destiny_client_v1,
            storage_url,
        )
        summary = await poll_batch_status(
            destiny_client_v1, import_record_id, import_batch_id
        )

    assert sum(summary["results"].values()) == n_refs
    assert summary["results"]["completed"] == n_refs
    assert not summary["failure_details"]

    # Check the references are in the database
    pg_result = await pg_session.execute(text("SELECT id FROM reference;"))
    reference_ids = {row[0] for row in pg_result.fetchall()}
    assert len(reference_ids) == n_refs

    # Check the references are in Elasticsearch
    await refresh_reference_index(es_client)
    es_result = await es_client.count(index=ReferenceDocument.Index.name)
    assert es_result["count"] == n_refs

    # Decisions should be canonical (as there's no other references in the system) or
    # unsearchable (as the data is random so may not have everything required).
    for reference in reference_ids:
        decision = await poll_duplicate_process(pg_session, reference)
        assert decision["duplicate_determination"] in (
            DuplicateDetermination.CANONICAL,
            DuplicateDetermination.UNSEARCHABLE,
        )
        assert decision["active_decision"]

    # Check automations have triggered
    for reference in reference_ids:
        pe = await poll_pending_enhancement(
            pg_session, reference, robot_automation_on_all_imports
        )
        assert pe["status"].casefold() == PendingEnhancementStatus.PENDING.casefold()
        assert not pe["robot_enhancement_batch_id"]
