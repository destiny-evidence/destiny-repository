from uuid import uuid4

import pytest

from app.core.exceptions import ParseError
from app.domain.references.models.models import ExternalIdentifierType
from app.domain.references.models.validators import (
    ExternalIdentifierParseResult,
    parse_identifier_lookup_from_string,
)


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        # Valid UUID, no type
        (
            str(uuid4()),
            {"identifier_type": None, "other_identifier_name": None, "error": None},
        ),
        # Known types
        (
            "doi:some-id",
            {
                "identifier_type": ExternalIdentifierType.DOI,
                "other_identifier_name": None,
                "error": None,
            },
        ),
        (
            "pm_id:some-id",
            {
                "identifier_type": ExternalIdentifierType.PM_ID,
                "other_identifier_name": None,
                "error": None,
            },
        ),
        (
            "open_alex:some-id",
            {
                "identifier_type": ExternalIdentifierType.OPEN_ALEX,
                "other_identifier_name": None,
                "error": None,
            },
        ),
        # OTHER with name
        (
            "other:CustomName:12345",
            {
                "identifier_type": ExternalIdentifierType.OTHER,
                "other_identifier_name": "CustomName",
                "error": None,
            },
        ),
        # Invalid: not a UUID, no delimiter
        ("not-a-uuid", {"error": "Must be UUIDv4"}),
        ("1234-5678-90ab", {"error": "Must be UUIDv4"}),
        # Unknown type
        ("unknown_type:id", {"error": "Unknown identifier type"}),
        # Valid parsing of ID with a colon
        (
            "doi:10.1000/xyz:123",
            {
                "identifier_type": ExternalIdentifierType.DOI,
                "other_identifier_name": None,
                "error": None,
            },
        ),
    ],
)
def test_parse_identifier_lookup_from_string_cases(input_str, expected):
    if expected["error"]:
        with pytest.raises(ParseError) as exc:
            parse_identifier_lookup_from_string(input_str)
        assert expected["error"] in str(exc.value)
    else:
        res = parse_identifier_lookup_from_string(input_str)
        if input_str.startswith("other"):
            identifier = input_str.split(":", 2)[2]
        elif ":" in input_str:
            identifier = input_str.split(":", 1)[1]
        else:
            identifier = input_str
        assert res.identifier == identifier
        assert res.identifier_type == expected["identifier_type"]
        assert res.other_identifier_name == expected["other_identifier_name"]


class TestExternalIdentifierParseResultDOICleanup:
    """Test DOI cleanup and safety checks during import parsing."""

    def test_clean_doi_strips_url_prefix(self):
        """Test that URL prefixes are stripped from DOIs on import."""
        raw = {
            "identifier": "https://doi.org/10.1234/example",
            "identifier_type": "doi",
        }
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        assert result.external_identifier.identifier == "10.1234/example"
        assert result.error is None

    def test_clean_doi_strips_query_params(self):
        """Test that query parameters are stripped from DOIs on import."""
        raw = {
            "identifier": "10.1234/example?utm_source=twitter",
            "identifier_type": "doi",
        }
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        assert result.external_identifier.identifier == "10.1234/example"
        assert result.error is None

    def test_clean_doi_unescapes_html_entities(self):
        """Test that HTML entities are unescaped in DOIs on import."""
        raw = {"identifier": "10.1234/example&amp;test", "identifier_type": "doi"}
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        assert result.external_identifier.identifier == "10.1234/example&test"
        assert result.error is None

    def test_clean_doi_strips_path_suffix(self):
        """Test that path suffixes like /pdf are stripped from DOIs on import."""
        raw = {"identifier": "10.1234/example/pdf", "identifier_type": "doi"}
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        assert result.external_identifier.identifier == "10.1234/example"
        assert result.error is None

    def test_skip_unsafe_doi_funder(self):
        """Test that funder DOIs (10.13039/*) are skipped on import."""
        raw = {"identifier": "10.13039/501100000780", "identifier_type": "doi"}
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is None
        assert result.error is not None
        assert "unsafe DOI" in result.error

    def test_skip_unsafe_doi_template(self):
        """Test that template DOIs (containing %) are skipped on import."""
        raw = {"identifier": "10.5007/%x", "identifier_type": "doi"}
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is None
        assert result.error is not None
        assert "unsafe DOI" in result.error

    def test_valid_doi_unchanged(self):
        """Test that clean, valid DOIs pass through unchanged."""
        raw = {"identifier": "10.1234/example", "identifier_type": "doi"}
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        assert result.external_identifier.identifier == "10.1234/example"
        assert result.error is None

    def test_non_doi_identifiers_unchanged(self):
        """Test that non-DOI identifiers are not affected by DOI cleanup."""
        raw = {"identifier": "W1234567890", "identifier_type": "open_alex"}
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        assert result.external_identifier.identifier == "W1234567890"
        assert result.error is None

    def test_complex_doi_cleanup(self):
        """Test cleanup of a DOI with multiple issues."""
        raw = {
            "identifier": "https://doi.org/10.1234/example?utm_source=web&magic=test/pdf",
            "identifier_type": "doi",
        }
        result = ExternalIdentifierParseResult.from_raw(raw, 1)

        assert result.external_identifier is not None
        # Should strip prefix, query params
        assert result.external_identifier.identifier == "10.1234/example"
        assert result.error is None
