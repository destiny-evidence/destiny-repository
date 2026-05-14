"""Unit tests for RobotService."""

import pytest

from app.api.auth import Entitlement
from app.core.exceptions import AuthError
from app.domain.robots.service import RobotService
from app.domain.robots.services.access_control_service import (
    RobotAccessControlService,
)
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from tests.factories import RobotFactory


@pytest.mark.asyncio
async def test_update_robot_preserves_entitlements_for_non_writer(
    fake_repository, fake_uow
):
    """A non-writer can PUT with empty entitlements without wiping them."""
    existing = RobotFactory(
        entitlements=frozenset({Entitlement.FULL_TEXT}),
        client_secret="secret",
    )
    repo = fake_repository(init_entries=[existing])
    uow = fake_uow(robots=repo)
    service = RobotService(RobotAntiCorruptionService(), uow)
    acl = RobotAccessControlService(entitlements=frozenset())

    submitted = existing.model_copy(update={"entitlements": frozenset()})
    result = await service.update_robot(robot=submitted, access_control_service=acl)

    assert result.entitlements == frozenset({Entitlement.FULL_TEXT})


@pytest.mark.asyncio
async def test_update_robot_rejects_non_writer_attempting_grant(
    fake_repository, fake_uow
):
    """A non-writer cannot grant entitlements via PUT."""
    existing = RobotFactory(entitlements=frozenset(), client_secret="secret")
    repo = fake_repository(init_entries=[existing])
    uow = fake_uow(robots=repo)
    service = RobotService(RobotAntiCorruptionService(), uow)
    acl = RobotAccessControlService(entitlements=frozenset())

    submitted = existing.model_copy(
        update={"entitlements": frozenset({Entitlement.FULL_TEXT})}
    )

    with pytest.raises(AuthError):
        await service.update_robot(robot=submitted, access_control_service=acl)


@pytest.mark.asyncio
async def test_get_robot_auth_info_returns_secret_and_entitlements(
    fake_repository, fake_uow
):
    """HMAC lookup surfaces both the secret and the stored entitlements."""
    robot = RobotFactory(
        entitlements=frozenset({Entitlement.FULL_TEXT}),
        client_secret="very-secret",
    )
    repo = fake_repository(init_entries=[robot])
    uow = fake_uow(robots=repo)
    service = RobotService(RobotAntiCorruptionService(), uow)

    auth_info = await service.get_robot_auth_info(robot.id)

    assert auth_info.secret == "very-secret"
    assert auth_info.entitlements == frozenset({Entitlement.FULL_TEXT})
