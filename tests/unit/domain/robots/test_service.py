"""Unit tests for RobotService entitlement handling."""

import pytest
from destiny_sdk.robots import RobotEntitlement

from app.api.auth import Entitlement
from app.core.exceptions import AuthError
from app.domain.robots.service import RobotService, _resolve_robot_entitlements
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from tests.factories import RobotFactory


def test_resolve_writer_can_set_arbitrary_entitlements():
    result = _resolve_robot_entitlements(
        submitted=frozenset({RobotEntitlement.FULL_TEXT}),
        existing=frozenset(),
        caller_entitlements=frozenset({Entitlement.ROBOT_ENTITLEMENT_WRITER}),
    )
    assert result == frozenset({RobotEntitlement.FULL_TEXT})


def test_resolve_writer_can_revoke_via_empty():
    result = _resolve_robot_entitlements(
        submitted=frozenset(),
        existing=frozenset({RobotEntitlement.FULL_TEXT}),
        caller_entitlements=frozenset({Entitlement.ROBOT_ENTITLEMENT_WRITER}),
    )
    assert result == frozenset()


def test_resolve_non_writer_empty_preserves_existing():
    result = _resolve_robot_entitlements(
        submitted=frozenset(),
        existing=frozenset({RobotEntitlement.FULL_TEXT}),
        caller_entitlements=frozenset(),
    )
    assert result == frozenset({RobotEntitlement.FULL_TEXT})


def test_resolve_non_writer_matching_passes_through():
    existing = frozenset({RobotEntitlement.FULL_TEXT})
    result = _resolve_robot_entitlements(
        submitted=existing,
        existing=existing,
        caller_entitlements=frozenset(),
    )
    assert result == existing


def test_resolve_non_writer_mismatched_non_empty_raises():
    with pytest.raises(AuthError) as exc:
        _resolve_robot_entitlements(
            submitted=frozenset({RobotEntitlement.FULL_TEXT}),
            existing=frozenset(),
            caller_entitlements=frozenset(),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_robot_preserves_entitlements_for_non_writer(
    fake_repository, fake_uow
):
    """A non-writer can PUT with empty entitlements without wiping them."""
    existing = RobotFactory(
        entitlements=frozenset({RobotEntitlement.FULL_TEXT}),
        client_secret="secret",
    )
    repo = fake_repository(init_entries=[existing])
    uow = fake_uow(robots=repo)
    service = RobotService(RobotAntiCorruptionService(), uow)

    submitted = existing.model_copy(update={"entitlements": frozenset()})
    result = await service.update_robot(
        robot=submitted, caller_entitlements=frozenset()
    )

    assert result.entitlements == frozenset({RobotEntitlement.FULL_TEXT})


@pytest.mark.asyncio
async def test_update_robot_rejects_non_writer_attempting_grant(
    fake_repository, fake_uow
):
    """A non-writer cannot grant entitlements via PUT."""
    existing = RobotFactory(entitlements=frozenset(), client_secret="secret")
    repo = fake_repository(init_entries=[existing])
    uow = fake_uow(robots=repo)
    service = RobotService(RobotAntiCorruptionService(), uow)

    submitted = existing.model_copy(
        update={"entitlements": frozenset({RobotEntitlement.FULL_TEXT})}
    )

    with pytest.raises(AuthError):
        await service.update_robot(robot=submitted, caller_entitlements=frozenset())


@pytest.mark.asyncio
async def test_get_robot_auth_info_returns_secret_and_entitlements(
    fake_repository, fake_uow
):
    """HMAC lookup surfaces both the secret and the stored entitlements."""
    robot = RobotFactory(
        entitlements=frozenset({RobotEntitlement.FULL_TEXT}),
        client_secret="very-secret",
    )
    repo = fake_repository(init_entries=[robot])
    uow = fake_uow(robots=repo)
    service = RobotService(RobotAntiCorruptionService(), uow)

    auth_info = await service.get_robot_auth_info(robot.id)

    assert auth_info.secret == "very-secret"
    assert auth_info.entitlements == frozenset({RobotEntitlement.FULL_TEXT})
