"""Utility functions for date and time handling."""

import datetime


def utc_now() -> datetime.datetime:
    """Return the current UTC time."""
    return datetime.datetime.now(datetime.UTC)
