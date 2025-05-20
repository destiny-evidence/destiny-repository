"""Test authentication bypass for local environments."""

from collections.abc import Callable
from unittest.mock import Mock

from app.core.auth import SuccessAuth


async def test_fake_auth_success(generate_fake_token: Callable[..., str]):
    """Test that our fake auth method succeeds on demand, with and without tokens."""
    auth = SuccessAuth()
    creds = Mock(credentials=generate_fake_token())

    assert await auth(creds)
    assert await auth(None)
