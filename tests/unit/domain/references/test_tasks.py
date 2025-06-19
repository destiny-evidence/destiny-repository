"""Unit tests for the tasks module in the references domain."""

import uuid
from unittest.mock import AsyncMock

from app.domain.references.models.models import BatchEnhancementRequest
from app.domain.references.service import ReferenceService
from app.domain.references.tasks import (
    collect_and_dispatch_references_for_batch_enhancement,
    request_default_enhancements,
)
from app.domain.robots.models import Robot
from app.domain.robots.service import RobotService


async def test_request_default_enhancements(monkeypatch, fake_uow):
    """
    Test the request_default_enhancements task distributor.

    Only tests function signatures, functionality itself is tested in the service layer.
    """
    in_reference_ids = {uuid.uuid4(), uuid.uuid4()}

    async def get_fake_uow():
        return fake_uow()

    monkeypatch.setattr(
        "app.domain.references.tasks.get_sql_unit_of_work",
        get_fake_uow,
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.get_es_unit_of_work",
        get_fake_uow,
    )

    mock_get_robots = AsyncMock(
        return_value=[
            r1 := Robot(
                id=uuid.uuid4(),
                name="Test Robot 1",
                base_url="http://robot1.example.com",
                owner="owner1",
                description="Does stuff by default",
                enhance_incoming_references=True,
            ),
            Robot(
                id=uuid.uuid4(),
                name="Test Robot 2",
                base_url="http://robot2.example.com",
                owner="owner2",
                description="Doesn't do stuff by default",
                enhance_incoming_references=False,
            ),
        ]
    )
    monkeypatch.setattr(RobotService, "get_robots_standalone", mock_get_robots)

    expected_request = BatchEnhancementRequest(
        reference_ids=in_reference_ids,
        robot_id=r1.id,
        id=uuid.uuid4(),
        status="RECEIVED",
    )
    mock_register_request = AsyncMock(return_value=expected_request)
    monkeypatch.setattr(
        ReferenceService,
        "register_batch_reference_enhancement_request",
        mock_register_request,
    )

    mock_collect_and_dispatch_request_to_robot = AsyncMock()
    monkeypatch.setattr(
        collect_and_dispatch_references_for_batch_enhancement,
        "kiq",
        mock_collect_and_dispatch_request_to_robot,
    )

    requests = await request_default_enhancements(reference_ids=in_reference_ids)
    assert len(requests) == 1
    assert requests[0] == expected_request

    mock_get_robots.assert_awaited_once_with()
    mock_register_request.assert_awaited_once()
    assert (
        set(mock_register_request.call_args[1]["enhancement_request"].reference_ids)
        == in_reference_ids
    )
    assert mock_register_request.call_args[1]["enhancement_request"].robot_id == r1.id
    mock_collect_and_dispatch_request_to_robot.assert_awaited_once_with(
        batch_enhancement_request_id=expected_request.id,
    )
