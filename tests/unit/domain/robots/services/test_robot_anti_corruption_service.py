"""Tests for RobotAntiCorruptionService."""

import uuid

import destiny_sdk
import pytest
from pydantic import BaseModel, SecretStr

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.robots.models.models import Robot
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)


class TestRobotAntiCorruptionService:
    """Test suite for RobotAntiCorruptionService."""

    @pytest.fixture
    def service(self):
        """Create a RobotAntiCorruptionService instance."""
        return RobotAntiCorruptionService()

    @pytest.fixture
    def robot_in_data(self):
        """Create SDK RobotIn test data."""
        return destiny_sdk.robots.RobotIn(
            name="Test Robot",
            description="A test robot for unit testing",
            owner="Test Owner",
        )

    @pytest.fixture
    def robot_data(self):
        """Create SDK Robot test data."""
        return destiny_sdk.robots.Robot(
            id=uuid.uuid7(),
            name="Test Robot",
            description="A test robot for unit testing",
            owner="Test Owner",
        )

    @pytest.fixture
    def domain_robot(self):
        """Create a domain Robot instance."""
        return Robot(
            id=uuid.uuid7(),
            name="Test Robot",
            description="A test robot for unit testing",
            owner="Test Owner",
            client_secret=SecretStr("test-secret-123"),
        )

    def test_round_trip_robot_in_to_sdk(self, service, robot_in_data):
        """Test round-trip conversion: SDK RobotIn -> Domain -> SDK Robot."""
        domain_robot = service.robot_from_sdk(robot_in_data)
        sdk_robot = service.robot_to_sdk(domain_robot)

        assert sdk_robot.id is not None
        assert sdk_robot.id == domain_robot.id
        assert sdk_robot.name == robot_in_data.name == domain_robot.name
        assert (
            sdk_robot.description
            == robot_in_data.description
            == domain_robot.description
        )
        assert sdk_robot.owner == robot_in_data.owner == domain_robot.owner

    def test_round_trip_robot_to_sdk(self, service, robot_data):
        """Test round-trip conversion: SDK Robot -> Domain -> SDK Robot."""
        domain_robot = service.robot_from_sdk(robot_data)
        sdk_robot = service.robot_to_sdk(domain_robot)

        assert sdk_robot.id == robot_data.id == domain_robot.id
        assert sdk_robot.name == robot_data.name == domain_robot.name
        assert (
            sdk_robot.description == robot_data.description == domain_robot.description
        )
        assert sdk_robot.owner == robot_data.owner == domain_robot.owner

    def test_domain_to_provisioned(self, service, domain_robot):
        """Test round-trip conversion: Domain -> SDK ProvisionedRobot -> Domain."""
        sdk_provisioned = service.robot_to_sdk_provisioned(domain_robot)

        assert domain_robot.get_client_secret() == sdk_provisioned.client_secret
        assert domain_robot.id == sdk_provisioned.id
        assert domain_robot.name == sdk_provisioned.name
        assert domain_robot.description == sdk_provisioned.description
        assert domain_robot.owner == sdk_provisioned.owner

    def test_invalid_robot_in(self, service):
        """Test conversion failure for invalid RobotIn data."""

        class BrokenRobotIn(BaseModel):
            name: str

        with pytest.raises(SDKToDomainError):
            service.robot_from_sdk(BrokenRobotIn(name="Invalid Robot"))

    def test_invalid_robot(self, service):
        """Test conversion failure for invalid Robot data."""

        class BrokenRobot(BaseModel):
            name: str

        with pytest.raises(DomainToSDKError):
            service.robot_to_sdk(BrokenRobot(name="Invalid Robot"))
