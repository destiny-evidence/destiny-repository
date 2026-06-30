"""Tests for import storage URL domain allowlisting."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import HttpUrl

from app.utils.validate_url import validate_storage_url


@pytest.fixture
def _remote_settings() -> Iterator[MagicMock]:
    with patch("app.utils.validate_url.get_settings") as mock:
        mock.return_value.running_locally = False
        mock.return_value.allowed_import_domains = ["blob.core.windows.net"]
        yield mock


@pytest.mark.parametrize(
    ("url", "should_pass"),
    [
        pytest.param(
            "https://myaccount.blob.core.windows.net/data.jsonl",
            True,
            id="subdomain-match",
        ),
        pytest.param(
            "https://blob.core.windows.net/data.jsonl",
            True,
            id="exact-match",
        ),
        pytest.param(
            "https://myaccount.Blob.Core.Windows.Net/data.jsonl",
            True,
            id="case-insensitive",
        ),
        pytest.param(
            "https://otherprovider.example.com/data.jsonl",
            False,
            id="disallowed-domain",
        ),
        pytest.param(
            "https://notblob.core.windows.net/data.jsonl",
            False,
            id="dot-boundary",
        ),
        pytest.param(
            "https://mybucket.s3.amazonaws.com/data.jsonl",
            False,
            id="different-provider",
        ),
    ],
)
@pytest.mark.usefixtures("_remote_settings")
def test_domain_matching(url: str, *, should_pass: bool) -> None:
    """Domain suffix matching with dot boundary, case-insensitive."""
    parsed = HttpUrl(url)
    if should_pass:
        assert validate_storage_url(parsed) == parsed
    else:
        with pytest.raises(ValueError, match="not allowed"):
            validate_storage_url(parsed)


def test_empty_allowlist_disables_check() -> None:
    """Empty allowlist disables the domain check — all URLs pass."""
    with patch("app.utils.validate_url.get_settings") as mock:
        mock.return_value.running_locally = False
        mock.return_value.allowed_import_domains = []
        url = HttpUrl("https://anything.example.com/data.jsonl")
        assert validate_storage_url(url) == url


def test_running_locally_bypasses_check() -> None:
    """When running locally, all URLs pass regardless of domain."""
    with patch("app.utils.validate_url.get_settings") as mock:
        mock.return_value.running_locally = True
        mock.return_value.allowed_import_domains = ["blob.core.windows.net"]
        url = HttpUrl("https://otherprovider.example.com/data.jsonl")
        assert validate_storage_url(url) == url
