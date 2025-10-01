"""End-to-end tests for happy path imports."""

import datetime
from collections.abc import Callable, Mapping
from contextlib import _AsyncGeneratorContextManager
from uuid import UUID

import httpx
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_fixed

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    DuplicateDetermination,
    PendingEnhancementStatus,
)


async def submit_happy_import_batch(
    client: httpx.AsyncClient, storage_url: str, import_record_id: UUID | None = None
) -> tuple[UUID, UUID]:
    """Submit a happy path import batch."""
    if not import_record_id:
        response = await client.post(
            "/imports/records/",
            json={
                "processor_name": "Test Processor",
                "processor_version": "v0.0.1",
                "source_name": "Random",
                "expected_reference_count": -1,
            },
        )
        assert response.status_code == 201
        import_record = response.json()
        import_record_id = import_record["id"]
        assert import_record_id
        assert import_record["status"] == "created"
        assert datetime.datetime.strptime(
            import_record["searched_at"], "%Y-%m-%dT%H:%M:%S.%f%z"
        ) > datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(seconds=5)

    response = await client.post(
        f"/imports/records/{import_record_id}/batches/",
        json={"storage_url": storage_url},
    )
    assert response.status_code == 202
    import_batch = response.json()
    import_batch_id = import_batch["id"]
    assert import_batch_id
    assert response.json()["status"] == "created"
    assert response.json()["import_record_id"] == import_record_id

    return import_record_id, import_batch_id


@retry(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True)
async def poll_batch_status(
    client: httpx.AsyncClient,
    import_record_id: UUID,
    batch_id: UUID,
) -> dict:
    """Poll the batch status until it reaches a terminal status."""
    response = await client.get(
        f"/imports/records/{import_record_id}/batches/{batch_id}/summary/"
    )
    assert response.status_code == 200
    summary = response.json()
    if summary["import_batch_status"] not in (
        "completed",
        "failed",
        "partially_failed",
    ):
        msg = "Batch not yet complete"
        raise Exception(msg)  # noqa: TRY002
    return summary


@retry(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True)
async def poll_duplicate_process(
    session: AsyncSession,
    reference_id: UUID,
) -> Mapping:
    """Poll the duplicate process until it reaches a terminal status."""
    pg_result = await session.execute(
        text(
            "SELECT * FROM reference_duplicate_decision "
            "WHERE reference_id=:reference_id;"
        ),
        {"reference_id": reference_id},
    )
    decision = pg_result.mappings().first()
    if (
        not decision
        or decision["duplicate_determination"]
        not in DuplicateDetermination.get_terminal_states()
    ):
        msg = "Duplicate process not yet complete"
        raise Exception(msg)  # noqa: TRY002
    return decision


@retry(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True)
async def poll_pending_enhancement(
    session: AsyncSession, reference_id: UUID, robot_id: UUID
) -> Mapping:
    """Poll the pending enhancement until it reaches a terminal status."""
    pg_result = await session.execute(
        text(
            "SELECT * FROM pending_enhancement "
            "WHERE reference_id=:reference_id AND robot_id=:robot_id;"
        ),
        {"reference_id": reference_id, "robot_id": robot_id},
    )
    pending_enhancement = pg_result.mappings().first()
    if not pending_enhancement:
        msg = "Pending enhancement not yet complete"
        raise Exception(msg)  # noqa: TRY002
    return pending_enhancement


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
    """Test a simple import of references."""
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
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)
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
