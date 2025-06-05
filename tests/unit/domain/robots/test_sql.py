# Dummy domain object for testing conversion
import uuid

import pytest
from pydantic import HttpUrl, SecretStr

from app.domain.robots.sql import Robot


class DummyDomainRobot:
    def __init__(self, id, base_url, client_secret, description, name, owner):
        self.id = id
        self.base_url = base_url
        self.client_secret = client_secret
        self.description = description
        self.name = name
        self.owner = owner


@pytest.mark.asyncio
async def test_robot_to_and_from_domain():
    robot_id = uuid.uuid4()
    dummy_robot = DummyDomainRobot(
        id=robot_id,
        base_url=HttpUrl("http://127.0.0.1:8000"),
        client_secret=SecretStr("dlkfsdflglsfglfkglsdkgfds"),
        description="description",
        name="name",
        owner="owner",
    )

    # Convert from domain to SQL model
    sql_robot = await Robot.from_domain(dummy_robot)
    assert sql_robot.id == dummy_robot.id
    assert sql_robot.base_url == str(dummy_robot.base_url)
    assert sql_robot.client_secret == dummy_robot.client_secret.get_secret_value()
    assert sql_robot.description == dummy_robot.description
    assert sql_robot.name == dummy_robot.name
    assert sql_robot.owner == dummy_robot.owner

    # Convert from SQL model to domain
    domain_ref = await sql_robot.to_domain()
    assert domain_ref.id == dummy_robot.id
    assert domain_ref.base_url == dummy_robot.base_url
    assert domain_ref.client_secret == dummy_robot.client_secret
    assert domain_ref.description == dummy_robot.description
    assert domain_ref.name == dummy_robot.name
    assert domain_ref.owner == dummy_robot.owner
