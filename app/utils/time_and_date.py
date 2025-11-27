"""Utility functions for date and time handling."""

import datetime

from pydantic import TypeAdapter

# Leverage pydantic to parse and serialize ISO 8601 durations
# This happens automatically in models but allows us to do
# so arbitrarily as well.
iso8601_duration_adapter = TypeAdapter(datetime.timedelta)


def utc_now() -> datetime.datetime:
    """Return the current UTC time."""
    return datetime.datetime.now(datetime.UTC)


def apply_positive_timedelta(
    delta: datetime.timedelta,
    base: datetime.datetime | None = None,
) -> datetime.datetime:
    """Apply a time delta to a base time."""
    if delta <= datetime.timedelta(0):
        msg = "expires_at timedelta must be positive"
        raise ValueError(msg)
    return (base or utc_now()) + delta
