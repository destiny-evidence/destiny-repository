# Dummy domain object for testing conversion
from uuid import uuid7

import pytest
from pydantic import SecretStr

from app.api.auth import Entitlement
from app.domain.robots.models.sql import Robot


class DummyDomainRobot:
    def __init__(self, id, client_secret, description, name, owner, entitlements):
        self.id = id
        self.client_secret = client_secret
        self.description = description
        self.name = name
        self.owner = owner
        self.entitlements = entitlements


@pytest.mark.asyncio
async def test_robot_to_and_from_domain():
    robot_id = uuid7()
    dummy_robot = DummyDomainRobot(
        id=robot_id,
        client_secret=SecretStr("dlkfsdflglsfglfkglsdkgfds"),
        description="description",
        name="name",
        owner="owner",
        entitlements=frozenset({Entitlement.FULL_TEXT}),
    )

    # Convert from domain to SQL model
    sql_robot = Robot.from_domain(dummy_robot)
    assert sql_robot.id == dummy_robot.id
    assert sql_robot.client_secret == dummy_robot.client_secret.get_secret_value()
    assert sql_robot.description == dummy_robot.description
    assert sql_robot.name == dummy_robot.name
    assert sql_robot.owner == dummy_robot.owner
    assert sql_robot.entitlements == [Entitlement.FULL_TEXT.value]

    # Convert from SQL model to domain
    domain_ref = sql_robot.to_domain()
    assert domain_ref.id == dummy_robot.id
    assert domain_ref.client_secret == dummy_robot.client_secret
    assert domain_ref.description == dummy_robot.description
    assert domain_ref.name == dummy_robot.name
    assert domain_ref.owner == dummy_robot.owner
    assert domain_ref.entitlements == dummy_robot.entitlements
