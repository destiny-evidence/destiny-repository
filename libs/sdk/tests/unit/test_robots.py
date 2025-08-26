import uuid

import destiny_sdk
import pytest
from pydantic import HttpUrl, ValidationError


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
