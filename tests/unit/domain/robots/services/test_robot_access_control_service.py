"""Unit tests for RobotAccessControlService."""

import pytest

from app.api.auth import Entitlement
from app.core.exceptions import AuthError
from app.domain.robots.services.access_control_service import (
    RobotAccessControlService,
)


def test_writer_can_set_arbitrary_entitlements():
    acl = RobotAccessControlService(
        entitlements=frozenset({Entitlement.ROBOT_ENTITLEMENT_WRITER})
    )
    result = acl.resolve_robot_entitlements(
        submitted=frozenset({Entitlement.FULL_TEXT}),
        existing=frozenset(),
    )
    assert result == frozenset({Entitlement.FULL_TEXT})


def test_writer_can_revoke_via_empty():
    acl = RobotAccessControlService(
        entitlements=frozenset({Entitlement.ROBOT_ENTITLEMENT_WRITER})
    )
    result = acl.resolve_robot_entitlements(
        submitted=frozenset(),
        existing=frozenset({Entitlement.FULL_TEXT}),
    )
    assert result == frozenset()


def test_non_writer_empty_preserves_existing():
    acl = RobotAccessControlService(entitlements=frozenset())
    result = acl.resolve_robot_entitlements(
        submitted=frozenset(),
        existing=frozenset({Entitlement.FULL_TEXT}),
    )
    assert result == frozenset({Entitlement.FULL_TEXT})


def test_non_writer_matching_passes_through():
    existing = frozenset({Entitlement.FULL_TEXT})
    acl = RobotAccessControlService(entitlements=frozenset())
    result = acl.resolve_robot_entitlements(submitted=existing, existing=existing)
    assert result == existing


def test_non_writer_mismatched_non_empty_raises():
    acl = RobotAccessControlService(entitlements=frozenset())
    with pytest.raises(AuthError) as exc:
        acl.resolve_robot_entitlements(
            submitted=frozenset({Entitlement.FULL_TEXT}),
            existing=frozenset(),
        )
    assert exc.value.status_code == 403
