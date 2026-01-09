"""Test polling pending enhancements."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from secrets import choice
from typing import TYPE_CHECKING

import httpx
import pytest
from destiny_sdk.client import RobotClient
from destiny_sdk.enhancements import Enhancement
from destiny_sdk.references import Reference
from destiny_sdk.robots import (
    EnhancementRequestIn,
    EnhancementRequestStatus,
    RobotEnhancementBatch,
    RobotEnhancementBatchResult,
)
from pydantic import HttpUrl
from tenacity import Retrying, stop_after_attempt, wait_fixed
from testcontainers.core.container import DockerContainer

from app.domain.robots.models.models import Robot
from tests.factories import (
    AbstractContentEnhancementFactory,
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    LocationEnhancementFactory,
)

if TYPE_CHECKING:
    import factory


def _create_client(repo_url: HttpUrl) -> RobotClient:
    """Create a test client for API calls."""
    # For e2e tests, we use a dummy secret key and client_id since auth is bypassed
    return RobotClient(
        base_url=repo_url,
        secret_key="dummy_secret_key",
        client_id=uuid.uuid7(),
    )


async def _create_enhancement_request(
    repo_client: httpx.AsyncClient, robot_id: str, reference_ids: list[str]
) -> str:
    """Create an enhancement request and return request ID."""
    request_in = EnhancementRequestIn(robot_id=robot_id, reference_ids=reference_ids)
    response = await repo_client.post(
        "/enhancement-requests/",
        json=request_in.model_dump(mode="json"),
    )
    assert response.status_code == 202
    request_out = response.json()
    return request_out["id"]


async def _poll_robot_batches(  # noqa: PLR0913
    repo_client: httpx.AsyncClient,
    minio_proxy_client: httpx.AsyncClient,
    robot_id: str,
    reference_ids: list[str],
    request_id: str,
    count: int = 2,
    lease: str | None = None,
) -> tuple[list[str], list[list[str]], list[RobotEnhancementBatch]]:
    """Poll for robot enhancement batches and return batch data."""
    robot_enhancement_batch_ids = []
    batch_references = []
    robot_requests = []

    client = _create_client(HttpUrl(str(repo_client.base_url)))

    for _ in range(count):
        result = client.poll_robot_enhancement_batch(
            robot_id=uuid.UUID(robot_id), limit=2, lease=lease
        )
        assert result is not None

        robot_enhancement_batch_ids.append(str(result.id))
        robot_requests.append(result)
        reference_storage_file = await minio_proxy_client.get(
            "", params={"url": str(result.reference_storage_url)}
        )
        assert reference_storage_file.status_code == 200
        reference_lines = reference_storage_file.text.splitlines()
        assert len(reference_lines) == 2

        # Store references for this batch for creating results
        batch_ref_ids = []
        for line in reference_lines:
            reference = Reference.model_validate_json(line)
            assert str(reference.id) in reference_ids
            batch_ref_ids.append(str(reference.id))
        batch_references.append(batch_ref_ids)

        # Verify status changes to processing
        response = await repo_client.get(f"/enhancement-requests/{request_id}/")
        assert response.status_code == 200
        request_status = response.json()["request_status"]
        assert request_status == EnhancementRequestStatus.PROCESSING

    return robot_enhancement_batch_ids, batch_references, robot_requests


async def _submit_robot_results(
    minio_proxy_client: httpx.AsyncClient,
    robot_enhancement_batch_ids: list[str],
    batch_references: list[list[str]],
    robot_requests: list[RobotEnhancementBatch],
    repo_url: HttpUrl,
) -> None:
    """Submit robot enhancement batch results."""
    allowed_robot_enhancements: list[factory.Factory] = [
        BibliographicMetadataEnhancementFactory,
        AbstractContentEnhancementFactory,
        AnnotationEnhancementFactory,
        LocationEnhancementFactory,
    ]

    for i, (batch_id, robot_request) in enumerate(
        zip(robot_enhancement_batch_ids, robot_requests, strict=True)
    ):
        result_entries = []

        for ref_id in batch_references[i]:
            enhancement = Enhancement(
                **EnhancementFactory.build(
                    reference_id=ref_id,
                    # Don't generate any raw enhancements as robots aren't allowed
                    # to generate these.
                    content=choice(allowed_robot_enhancements).build(),
                ).model_dump()
            )
            result_entries.append(enhancement.to_jsonl())

        # Upload result file to the provided result storage URL
        result_content = "\n".join(result_entries)
        upload_response = await minio_proxy_client.put(
            "",
            params={"url": str(robot_request.result_storage_url)},
            content=result_content.encode("utf-8"),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload_response.status_code == 200

        robot_result = RobotEnhancementBatchResult(request_id=batch_id, error=None)

        client = _create_client(repo_url)
        result = client.send_robot_enhancement_batch_result(robot_result)
        assert result is not None


async def _wait_for_enhancement_request_status(
    repo_client: httpx.AsyncClient,
    request_id: str,
    expected_status: EnhancementRequestStatus,
    max_attempts: int = 3,
    wait_seconds: int = 1,
) -> None:
    """Wait for an enhancement request to reach the expected status."""
    for attempt in Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_fixed(wait_seconds),
        reraise=True,
    ):
        with attempt:
            response = await repo_client.get(f"/enhancement-requests/{request_id}/")
            assert response.status_code == 200
            response_status = response.json()["request_status"]
            if response_status != expected_status.value:
                msg = f"Status is {response_status}, expected {expected_status.value}"
                raise Exception(msg)  # noqa: TRY002


async def test_polling_pending_enhancements(
    destiny_client_v1: httpx.AsyncClient,
    robot: Robot,
    minio_proxy_client: httpx.AsyncClient,
    add_references: Callable[[int], Awaitable[set[uuid.UUID]]],
):
    """Test the happy path for a robot polling for pending enhancements."""
    reference_ids = [str(reference_id) for reference_id in await add_references(4)]
    robot_id = str(robot.id)
    repo_url = HttpUrl(str(destiny_client_v1.base_url))

    # Create enhancement request and verify initial status
    request_id = await _create_enhancement_request(
        destiny_client_v1, robot_id, reference_ids
    )
    response = await destiny_client_v1.get(f"/enhancement-requests/{request_id}/")
    assert response.status_code == 200
    request_status = response.json()["request_status"]
    assert request_status == EnhancementRequestStatus.RECEIVED

    batch_ids, batch_refs, robot_requests = await _poll_robot_batches(
        destiny_client_v1, minio_proxy_client, robot_id, reference_ids, request_id
    )

    # Verify no more batches available
    client = _create_client(repo_url)
    result = client.poll_robot_enhancement_batch(robot_id=robot.id, limit=2)
    assert result is None

    await _submit_robot_results(
        minio_proxy_client, batch_ids, batch_refs, robot_requests, repo_url
    )

    await _wait_for_enhancement_request_status(
        destiny_client_v1, request_id, EnhancementRequestStatus.COMPLETED
    )


async def send_expiry_task(worker: DockerContainer) -> None:
    """
    Execute the expiry task in the worker container.

    This is the same way it is executed in production via the scheduled container app
    job.
    """
    worker.exec(
        [
            "uv",
            "run",
            "python",
            "-m",
            "app.run_task",
            "app.domain.references.tasks:expire_and_replace_stale_pending_enhancements",
        ]
    )


async def test_cannot_submit_expired_enhancement_results(
    destiny_client_v1: httpx.AsyncClient,
    robot: Robot,
    minio_proxy_client: httpx.AsyncClient,
    worker: DockerContainer,
    add_references: Callable[[int], Awaitable[set[uuid.UUID]]],
):
    """Test that robots cannot submit results after pending enhancements expire."""
    reference_ids = [str(reference_id) for reference_id in await add_references(2)]
    robot_id = str(robot.id)
    repo_url = HttpUrl(str(destiny_client_v1.base_url))

    request_id = await _create_enhancement_request(
        destiny_client_v1, robot_id, reference_ids
    )

    batch_ids, batch_refs, batches = await _poll_robot_batches(
        destiny_client_v1,
        minio_proxy_client,
        robot_id,
        reference_ids,
        request_id,
        count=1,
        lease="PT2S",
    )
    await asyncio.sleep(3)  # Wait for lease to expire
    await send_expiry_task(worker)
    await asyncio.sleep(3)  # Wait for worker to process task

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _submit_robot_results(
            minio_proxy_client, batch_ids, batch_refs, batches, repo_url
        )

    assert exc_info.value.response.status_code == 422
    error_detail = exc_info.value.response.json()["detail"]
    assert "cannot process results" in error_detail.lower()
    assert "expired" in error_detail.lower()
    assert "importing" in error_detail.lower()


async def test_can_submit_results_after_renewing_lease(
    destiny_client_v1: httpx.AsyncClient,
    robot: Robot,
    minio_proxy_client: httpx.AsyncClient,
    worker: DockerContainer,
    add_references: Callable[[int], Awaitable[set[uuid.UUID]]],
):
    """Test that robots can submit results if they renew the lease before expiry."""
    reference_ids = [str(reference_id) for reference_id in await add_references(2)]
    robot_id = str(robot.id)
    repo_url = HttpUrl(str(destiny_client_v1.base_url))

    request_id = await _create_enhancement_request(
        destiny_client_v1, robot_id, reference_ids
    )

    batch_ids, batch_refs, batches = await _poll_robot_batches(
        destiny_client_v1,
        minio_proxy_client,
        robot_id,
        reference_ids,
        request_id,
        count=1,
        lease="PT2S",
    )

    renew_response = await destiny_client_v1.patch(
        f"/robot-enhancement-batches/{batch_ids[0]}/renew-lease/",
        params={"lease": "PT120S"},
    )
    assert renew_response.status_code == 200

    # Wait to ensure original lease would have expired
    await asyncio.sleep(3)
    await send_expiry_task(worker)
    await asyncio.sleep(3)  # Wait for worker to process task

    await _submit_robot_results(
        minio_proxy_client, batch_ids, batch_refs, batches, repo_url
    )

    await _wait_for_enhancement_request_status(
        destiny_client_v1, request_id, EnhancementRequestStatus.COMPLETED
    )
