from uuid import uuid7

import destiny_sdk
import pytest
from pydantic import ValidationError


def test_provisioned_robot_valid():
    provisioned_robot = destiny_sdk.robots.ProvisionedRobot(
        id=uuid7(),
        name="Mr. Roboto",
        description="I have come to help you with your problems",
        owner="Styx",
        client_secret="secret, secret, I've got a secret",
    )

    assert provisioned_robot.owner == "Styx"


def test_robot_models_reject_any_extra_fields():
    with pytest.raises(ValidationError):
        destiny_sdk.robots.Robot(
            name="Mr. Roboto",
            description="I have come to help you with your problems",
            owner="Styx",
            client_secret="I'm not allowed in this model",
        )


def test_enhancement_request_in_rejects_duplicate_reference_ids():
    ref_id = uuid7()
    with pytest.raises(ValidationError):
        destiny_sdk.robots.EnhancementRequestIn(
            robot_id=uuid7(),
            reference_ids=[ref_id, ref_id],
        )


def test_enhancement_request_in_allows_distinct_reference_ids():
    request = destiny_sdk.robots.EnhancementRequestIn(
        robot_id=uuid7(),
        reference_ids=[uuid7(), uuid7()],
    )
    assert len(request.reference_ids) == 2
