"""Unit tests for ReferenceAntiCorruptionService."""

import pytest

from app.core.exceptions import ParseError
from app.domain.references.models.models import PublicationYearRange
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)


class DummyBlobRepository:
    async def get_signed_url(self, *args, **kwargs):
        return "dummy_url"


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("[2000,2020]", PublicationYearRange(start=2000, end=2020)),
        ("(2000,2020]", PublicationYearRange(start=2001, end=2020)),
        ("[2000,2020)", PublicationYearRange(start=2000, end=2019)),
        ("(2000,2020)", PublicationYearRange(start=2001, end=2019)),
        ("[*,2020]", PublicationYearRange(start=None, end=2020)),
        ("[2000,*]", PublicationYearRange(start=2000, end=None)),
        ("[*,*]", PublicationYearRange(start=None, end=None)),
    ],
)
def test_publication_year_range_from_query_parameter_valid(input_str, expected):
    service = ReferenceAntiCorruptionService(blob_repository=DummyBlobRepository())
    result = service.publication_year_range_from_query_parameter(input_str)
    assert result == expected


@pytest.mark.parametrize(
    "input_str",
    [
        "2000,2020",  # missing brackets
        "[2000,2020",  # missing end bracket
        "2000,2020]",  # missing start bracket
        "[2000-2020]",  # wrong delimiter
        "[2000,2020]extra",  # extra chars
        "[2000 2020]",  # missing comma
        "[*,2020",  # missing end bracket
    ],
)
def test_publication_year_range_from_query_parameter_invalid(input_str):
    service = ReferenceAntiCorruptionService(blob_repository=DummyBlobRepository())
    with pytest.raises(ParseError):
        service.publication_year_range_from_query_parameter(input_str)
