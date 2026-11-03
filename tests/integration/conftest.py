"""Fixtures shared by integration tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def blob_repository() -> MagicMock:
    """Stand in for the payload store, which these tests do not inspect."""
    blob_repository = MagicMock()
    blob_repository.upload_file_to_blob_storage = AsyncMock(
        return_value=MagicMock(to_uri=MagicMock(return_value="azure://payload"))
    )
    return blob_repository
