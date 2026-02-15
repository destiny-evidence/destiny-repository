"""Tests for SSRF mitigation in storage URL validation."""

import socket
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import HttpUrl

from app.utils.validate_url import (
    _cache,
    validate_storage_url,
    validate_storage_url_async,
)

TEST_URL = HttpUrl("https://example.com/data.jsonl")


def _addrinfo(ip: str) -> list[tuple]:
    """Build a getaddrinfo return value for an IPv4 or IPv6 address."""
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Ensure validation cache is empty for each test."""
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def _remote_settings() -> Iterator[MagicMock]:
    with patch("app.utils.validate_url.get_settings") as mock:
        mock.return_value.running_locally = False
        yield mock


@pytest.mark.parametrize(
    "ip",
    [
        pytest.param("10.0.0.1", id="ipv4-private"),
        pytest.param("::1", id="ipv6-loopback"),
    ],
)
@pytest.mark.usefixtures("_remote_settings")
def test_blocked_private_addresses(ip: str) -> None:
    """Non-global addresses are rejected without leaking the IP."""
    with patch(
        "app.utils.validate_url.socket.getaddrinfo",
        return_value=_addrinfo(ip),
    ):
        with pytest.raises(ValueError, match="disallowed address") as exc_info:
            validate_storage_url(TEST_URL)
        assert ip not in str(exc_info.value)


@pytest.mark.usefixtures("_remote_settings")
def test_allowed_public_ip() -> None:
    """Public IPs pass validation."""
    addrinfo = _addrinfo("93.184.216.34")
    with patch(
        "app.utils.validate_url.socket.getaddrinfo",
        return_value=addrinfo,
    ):
        assert validate_storage_url(TEST_URL) == TEST_URL


@pytest.mark.usefixtures("_remote_settings")
def test_unresolvable_hostname() -> None:
    """Unresolvable hostnames raise ValueError."""
    with (
        patch(
            "app.utils.validate_url.socket.getaddrinfo",
            side_effect=socket.gaierror("Name resolution failed"),
        ),
        pytest.raises(ValueError, match="Could not resolve"),
    ):
        validate_storage_url(HttpUrl("https://nonexistent.invalid/data.jsonl"))


def test_running_locally_skips_checks() -> None:
    """When running locally, private IPs are allowed."""
    with (
        patch(
            "app.utils.validate_url.socket.getaddrinfo",
            return_value=_addrinfo("10.0.0.1"),
        ),
        patch("app.utils.validate_url.get_settings") as mock_settings,
    ):
        mock_settings.return_value.running_locally = True
        assert validate_storage_url(TEST_URL) == TEST_URL


@pytest.mark.usefixtures("_remote_settings")
def test_cache_skips_dns_on_repeat_call() -> None:
    """Repeated calls for the same host skip DNS resolution."""
    addrinfo = _addrinfo("93.184.216.34")
    with patch(
        "app.utils.validate_url.socket.getaddrinfo",
        return_value=addrinfo,
    ) as mock_getaddrinfo:
        validate_storage_url(TEST_URL)
        validate_storage_url(TEST_URL)
        assert mock_getaddrinfo.call_count == 1


@pytest.mark.usefixtures("_remote_settings")
@pytest.mark.asyncio
async def test_async_cache_hit_skips_thread_dispatch() -> None:
    """Async wrapper returns immediately from cache without calling to_thread."""
    addrinfo = _addrinfo("93.184.216.34")
    with patch(
        "app.utils.validate_url.socket.getaddrinfo",
        return_value=addrinfo,
    ):
        # Prime the cache via sync path
        validate_storage_url(TEST_URL)

    with patch("app.utils.validate_url.asyncio.to_thread") as mock_to_thread:
        result = await validate_storage_url_async(TEST_URL)
        assert result == TEST_URL
        mock_to_thread.assert_not_called()


@pytest.mark.usefixtures("_remote_settings")
def test_cache_does_not_cache_failures() -> None:
    """Failed validations are not cached — retries hit DNS again."""
    with patch(
        "app.utils.validate_url.socket.getaddrinfo",
        return_value=_addrinfo("10.0.0.1"),
    ) as mock_getaddrinfo:
        with pytest.raises(ValueError, match="disallowed address"):
            validate_storage_url(TEST_URL)
        with pytest.raises(ValueError, match="disallowed address"):
            validate_storage_url(TEST_URL)
        assert mock_getaddrinfo.call_count == 2
