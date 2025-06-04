# Dummy domain object for testing conversion
import uuid

import destiny_sdk
import pytest
from pydantic import HttpUrl, SecretStr

from app.domain.robots.sql import Robot


class DummyDomainRobot:
    def __init__(
        self,
        id,
        robot_base_url,
        dependent_enhancements,
        dependent_identifiers,
        robot_secret,
    ):
        self.id = id
        self.robot_base_url = robot_base_url
        self.robot_secret = robot_secret
        self.dependent_enhancements = dependent_enhancements
        self.dependent_identifiers = dependent_identifiers


@pytest.mark.asyncio
async def test_robot_to_and_from_domain_without_dependencies():
    robot_id = uuid.uuid4()
    dummy_robot = DummyDomainRobot(
        id=robot_id,
        robot_base_url=HttpUrl("http://127.0.0.1:8000"),
        robot_secret=SecretStr("dlkfsdflglsfglfkglsdkgfds"),
        dependent_enhancements=[],
        dependent_identifiers=[],
    )

    # Convert from domain to SQL model
    sql_robot = await Robot.from_domain(dummy_robot)
    assert sql_robot.id == dummy_robot.id
    assert sql_robot.robot_base_url == str(dummy_robot.robot_base_url)
    assert sql_robot.robot_secret == dummy_robot.robot_secret.get_secret_value()
    assert sql_robot.dependent_enhancements is None
    assert sql_robot.dependent_identifiers is None

    # Convert from SQL model to domain
    domain_ref = await sql_robot.to_domain()
    assert domain_ref.id == dummy_robot.id
    assert domain_ref.robot_base_url == dummy_robot.robot_base_url
    assert domain_ref.robot_secret == dummy_robot.robot_secret
    assert domain_ref.dependent_enhancements == dummy_robot.dependent_enhancements
    assert domain_ref.dependent_identifiers == dummy_robot.dependent_identifiers


@pytest.mark.asyncio
async def test_robot_to_and_from_domain_with_dependencies():
    robot_id = uuid.uuid4()
    dummy_robot = DummyDomainRobot(
        id=robot_id,
        robot_base_url=HttpUrl("http://127.0.0.1:8000"),
        robot_secret=SecretStr("dlkfsdflglsfglfkglsdkgfds"),
        dependent_enhancements=[destiny_sdk.enhancements.EnhancementType.ANNOTATION],
        dependent_identifiers=[destiny_sdk.identifiers.ExternalIdentifierType.DOI],
    )

    # Convert from domain to SQL model
    sql_robot = await Robot.from_domain(dummy_robot)
    assert sql_robot.id == dummy_robot.id
    assert sql_robot.dependent_enhancements == [
        destiny_sdk.enhancements.EnhancementType.ANNOTATION.value
    ]
    assert sql_robot.dependent_identifiers == [
        destiny_sdk.identifiers.ExternalIdentifierType.DOI.value
    ]

    # Convert from SQL model to domain
    domain_ref = await sql_robot.to_domain()
    assert domain_ref.id == dummy_robot.id
    assert domain_ref.dependent_enhancements == dummy_robot.dependent_enhancements
    assert domain_ref.dependent_identifiers == dummy_robot.dependent_identifiers
