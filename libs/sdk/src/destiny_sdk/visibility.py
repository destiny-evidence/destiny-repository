"""Visibility enum for repository data."""

from enum import StrEnum, auto


class Visibility(StrEnum):
    """
    The visibility of a data element in the repository.

    This is used to manage whether information should be publicly available or
    restricted (generally due to copyright constraints from publishers).
    """

    PUBLIC = auto()
    """Visible to the general public without authentication."""
    RESTRICTED = auto()
    """Requires authentication to be visible."""
    HIDDEN = auto()
    """Is not visible, but may be passed to data mining processes."""
