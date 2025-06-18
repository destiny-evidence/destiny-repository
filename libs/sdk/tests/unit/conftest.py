import asyncio
import logging
from typing import Any

import pytest

MIGRATION_TASK: asyncio.Task | None = None

logging.getLogger("asyncio").setLevel("DEBUG")


@pytest.fixture(scope="session", autouse=True)
def anyio_backend() -> tuple[str, dict[str, Any]]:
    """Specify the anyio backend for async tests."""
    return "asyncio", {"use_uvloop": True}
