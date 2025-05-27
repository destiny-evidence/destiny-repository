"""Utility functions for list operations."""

from collections.abc import Generator


def list_chunker(lst: list, n: int) -> Generator[list, None, None]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
