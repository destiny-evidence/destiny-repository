"""Unit tests for the tasks module in the references domain."""

import uuid
from unittest.mock import AsyncMock

from app.domain.references.models.models import (
    BatchEnhancementRequest,
    RobotAutomationPercolationResult,
)
from app.domain.references.service import ReferenceService
from app.domain.references.tasks import (
    collect_and_dispatch_references_for_batch_enhancement,
    detect_and_dispatch_robot_automations,
)


async def test_robot_automations(monkeypatch, fake_uow):
    """
    Test the detect_and_dispatch_robot_automations task distributor.
    Only tests function signatures, functionality itself is tested in the service layer.
    """
    in_reference_ids = {uuid.uuid4(), uuid.uuid4()}
    in_enhancement_ids = {uuid.uuid4(), uuid.uuid4()}
    robot_id = uuid.uuid4()

    expected_request = BatchEnhancementRequest(
        reference_ids=in_reference_ids,
        robot_id=robot_id,
        id=uuid.uuid4(),
        status="RECEIVED",
        source="test_source",
    )
    mock_register_request = AsyncMock(return_value=expected_request)
    monkeypatch.setattr(
        ReferenceService,
        "register_batch_reference_enhancement_request",
        mock_register_request,
    )

    mock_detect_robot_automations = AsyncMock(
        return_value=[
            RobotAutomationPercolationResult(
                robot_id=robot_id, reference_ids=in_reference_ids
            )
        ]
    )
    monkeypatch.setattr(
        ReferenceService,
        "detect_robot_automations",
        mock_detect_robot_automations,
    )

    mock_collect_and_dispatch_request_to_robot = AsyncMock()
    monkeypatch.setattr(
        collect_and_dispatch_references_for_batch_enhancement,
        "kiq",
        mock_collect_and_dispatch_request_to_robot,
    )

    requests = await detect_and_dispatch_robot_automations(
        reference_service=ReferenceService(fake_uow()),
        reference_ids=in_reference_ids,
        enhancement_ids=in_enhancement_ids,
        source_str="test_source",
    )
    assert len(requests) == 1
    assert requests[0] == expected_request

    mock_register_request.assert_awaited_once()
    assert (
        set(mock_register_request.call_args[1]["enhancement_request"].reference_ids)
        == in_reference_ids
    )
    assert (
        mock_register_request.call_args[1]["enhancement_request"].robot_id == robot_id
    )
    mock_collect_and_dispatch_request_to_robot.assert_awaited_once_with(
        batch_enhancement_request_id=expected_request.id,
    )
    mock_detect_robot_automations.assert_awaited_once_with(
        reference_ids=in_reference_ids, enhancement_ids=in_enhancement_ids
    )
