import uuid

import destiny_sdk
from pydantic import HttpUrl


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
