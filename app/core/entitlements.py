"""Entitlements granted to authenticated principals."""

from enum import StrEnum, auto


class Entitlement(StrEnum):
    """Capabilities that can be granted to an authenticated principal."""

    FULL_TEXT = auto()
    RAW_ENHANCEMENT_WRITER = auto()
    ROBOT_ENTITLEMENT_WRITER = auto()
