"""URL validation utilities for import storage URL domain allowlisting."""

from urllib.parse import urlparse

from pydantic import HttpUrl

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger

logger = get_logger(__name__)


def validate_storage_url(url: HttpUrl) -> HttpUrl:
    """
    Validate that a storage URL's hostname matches the domain allowlist.

    Rejects URLs whose hostname is not a suffix match (with dot boundary)
    against ``settings.allowed_import_domains``.

    Bypass conditions (returns immediately):
    - ``settings.running_locally`` is True
    - ``allowed_import_domains`` is empty (check disabled)

    Raises ValueError with a generic message on rejection. The log message
    includes the hostname but never the allowlist itself.
    """
    parsed = urlparse(str(url))
    hostname = parsed.hostname
    if not hostname:
        msg = "storage_url has no hostname."
        raise ValueError(msg)

    settings = get_settings()
    if settings.running_locally:
        return url

    allowed = settings.allowed_import_domains
    if not allowed:
        return url

    hostname_lower = hostname.lower()
    for domain in allowed:
        domain_lower = domain.lower()
        if hostname_lower == domain_lower or hostname_lower.endswith(
            "." + domain_lower
        ):
            return url

    logger.warning(
        "Storage URL hostname %s rejected by domain allowlist",
        hostname,
    )
    msg = "storage_url hostname is not allowed."
    raise ValueError(msg)
