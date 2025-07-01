import uuid

import destiny_sdk
import pytest
from pydantic import HttpUrl, ValidationError


def test_enhancement_request_valid():
    enhancement_request = destiny_sdk.robots.EnhancementRequestRead(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        reference=destiny_sdk.references.Reference(
            id=uuid.uuid4(), visibility=destiny_sdk.visibility.Visibility.RESTRICTED
        ),
        robot_id=uuid.uuid4(),
        request_status=destiny_sdk.robots.EnhancementRequestStatus.RECEIVED,
    )

    assert (
        enhancement_request.request_status
        == destiny_sdk.robots.EnhancementRequestStatus.RECEIVED
    )
    assert enhancement_request.enhancement_parameters is None
    assert enhancement_request.error is None


def test_provisioned_robot_valid():
    provisioned_robot = destiny_sdk.robots.ProvisionedRobot(
        id=uuid.uuid4(),
        base_url=HttpUrl("https://www.domo-arigato-mr-robo.to"),
        name="Mr. Roboto",
        description="I have come to help you with your problems",
        owner="Styx",
        client_secret="secret, secret, I've got a secret",
    )

    assert provisioned_robot.owner == "Styx"


def test_robot_models_reject_any_extra_fields():
    with pytest.raises(ValidationError):
        destiny_sdk.robots.Robot(
            base_url=HttpUrl("https://www.domo-arigato-mr-robo.to"),
            name="Mr. Roboto",
            description="I have come to help you with your problems",
            owner="Styx",
            client_secret="I'm not allowed in this model",
        )


def test_robot_request_does_not_require_extra_fields():
    reference = destiny_sdk.references.Reference(
        id=uuid.uuid4(), visibility=destiny_sdk.visibility.Visibility.RESTRICTED
    )

    # Don't pass any extra fields
    robot_request = destiny_sdk.robots.RobotRequest(
        id=uuid.uuid4(), reference=reference
    )

    assert not robot_request.extra_fields
