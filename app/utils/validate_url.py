"""URL validation utilities for SSRF (Server-Side Request Forgery) mitigation."""

import asyncio
import ipaddress
import socket
import threading
from urllib.parse import urlparse

from cachetools import TTLCache
from pydantic import HttpUrl

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger

logger = get_logger(__name__)

# Only successful validations are stored — DNS failures and blocked
# IPs are never cached so transient issues don't become sticky.
# Lock guards against concurrent access from asyncio.to_thread workers.
_cache: TTLCache[tuple[str, int], bool] = TTLCache(maxsize=1024, ttl=300)
_cache_lock = threading.Lock()


def validate_storage_url(url: HttpUrl) -> HttpUrl:
    """
    Validate that a storage URL does not resolve to a non-global IP.

    Prevents SSRF by resolving the hostname and rejecting any
    non-globally-routable address.

    When running locally, all IP checks are skipped (local dev storage
    typically runs on private IPs).

    Raises ValueError with a generic message on failure. Detailed info
    (resolved IPs) is logged server-side only to avoid leaking network
    topology to callers.

    Successful validations are cached per (hostname, port) with a TTL
    to avoid repeated DNS lookups for the same storage host.
    """
    parsed = urlparse(str(url))
    hostname = parsed.hostname
    if not hostname:
        msg = "storage_url has no hostname."
        raise ValueError(msg)

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    settings = get_settings()
    if settings.running_locally:
        return url

    cache_key = (hostname, port)
    with _cache_lock:
        if cache_key in _cache:
            return url

    try:
        addrinfos = socket.getaddrinfo(hostname, port)
    except socket.gaierror as exc:
        logger.warning("DNS resolution failed for storage_url hostname: %s", hostname)
        msg = "Could not resolve storage_url hostname."
        raise ValueError(msg) from exc

    for _family, _, _, _, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])

        if not ip.is_global:
            logger.warning(
                "SSRF blocked: storage_url hostname %s resolved to " "non-global IP %s",
                hostname,
                ip,
            )
            msg = "storage_url resolves to a disallowed address."
            raise ValueError(msg)

    with _cache_lock:
        _cache[cache_key] = True
    return url


async def validate_storage_url_async(url: HttpUrl) -> HttpUrl:
    """
    Async wrapper that runs DNS resolution off the event loop.

    Cache hits return immediately without dispatching to a thread.
    """
    parsed = urlparse(str(url))
    hostname = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with _cache_lock:
        if hostname and (hostname, port) in _cache:
            return url
    return await asyncio.to_thread(validate_storage_url, url)
