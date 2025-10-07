"""Utility functions for import end-to-end tests."""

import datetime
from collections.abc import Callable, Mapping
from contextlib import _AsyncGeneratorContextManager
from uuid import UUID

import httpx
from destiny_sdk.enhancements import EnhancementFileInput
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy import select, text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_fixed

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import DuplicateDetermination, Reference
from app.domain.references.models.sql import ReferenceDuplicateDecision


class TestPollingExhaustedError(Exception):
    """Error raised when polling fails."""


async def refresh_reference_index(es_client: AsyncElasticsearch) -> None:
    """
    Refresh the reference index.

    This just compresses race conditions in tests that check ES state immediately
    after an operation that modifies it.
    """
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


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


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1), reraise=True)
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
        raise TestPollingExhaustedError(msg)
    return summary


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1), reraise=True)
async def poll_duplicate_process(
    session: AsyncSession,
    reference_id: UUID,
    required_state: DuplicateDetermination | None = None,
) -> ReferenceDuplicateDecision:
    """Poll the duplicate process until it is in the required state."""
    query = select(ReferenceDuplicateDecision).where(
        ReferenceDuplicateDecision.reference_id == reference_id,
    )
    if required_state:
        query = query.where(
            ReferenceDuplicateDecision.duplicate_determination == required_state
        )
    else:
        query = query.where(ReferenceDuplicateDecision.active_decision)
    result = await session.execute(query)
    try:
        decision = result.scalar_one()
    except NoResultFound as exc:
        msg = "Reference duplicate decision not yet in required state"
        raise TestPollingExhaustedError(msg) from exc

    return decision


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1), reraise=True)
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
        msg = "Pending enhancement does not yet exist"
        raise TestPollingExhaustedError(msg)
    return pending_enhancement


async def import_references(
    client: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    references: list[Reference],
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
) -> set[UUID]:
    """
    Import references to the repository.

    Used for setting state in tests, not directly testing imports, and as such asserts
    import success.

    Does not return until deduplication has completed for all references.
    """
    async with get_import_file_signed_url(
        [
            ReferenceFileInput(
                visibility=r.visibility,
                enhancements=[
                    EnhancementFileInput(**e.model_dump()) for e in r.enhancements or []
                ],
                identifiers=[i.identifier for i in r.identifiers or []],
            )
            for r in references
        ]
    ) as storage_url:
        import_record_id, import_batch_id = await submit_happy_import_batch(
            client, storage_url
        )
        summary = await poll_batch_status(client, import_record_id, import_batch_id)

    await refresh_reference_index(es_client)

    assert summary["import_batch_status"] == "completed"
    assert summary["results"]["completed"] == len(references)

    pg_result = await pg_session.execute(
        text(
            "SELECT reference_id "
            "FROM import_result "
            "WHERE import_batch_id=:import_batch_id;"
        ),
        {"import_batch_id": import_batch_id},
    )
    reference_ids = {row[0] for row in pg_result.all()}
    for reference_id in reference_ids:
        await poll_duplicate_process(pg_session, reference_id)

    await refresh_reference_index(es_client)

    return reference_ids
