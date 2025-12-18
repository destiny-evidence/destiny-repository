import uuid

import destiny_sdk
import pytest
from pydantic import ValidationError


def test_valid_doi():
    obj = destiny_sdk.identifiers.DOIIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
        identifier="10.1000/xyz123",
    )
    assert obj.identifier == "10.1000/xyz123"


def test_invalid_doi():
    with pytest.raises(ValidationError, match="String should match pattern"):
        destiny_sdk.identifiers.DOIIdentifier(
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
            identifier="invalid_doi",
        )


def test_doi_url_removed():
    """Test that a DOI with a URL is fixed to just the DOI part."""
    obj = destiny_sdk.identifiers.DOIIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
        identifier="http://doi.org/10.1000/xyz123",
    )
    assert obj.identifier == "10.1000/xyz123"


def test_valid_eric_identifier():
    obj = destiny_sdk.identifiers.ERICIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.ERIC,
        identifier="EJ1480525",
    )

    assert obj.identifier == "EJ1480525"


def test_invalid_eric_identifier():
    with pytest.raises(ValidationError, match="String should match pattern"):
        destiny_sdk.identifiers.ERICIdentifier(
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.ERIC,
            identifier="CD15423432",
        )


def test_eric_identifier_url_removed():
    """Test that a ERIC number with a URL is fixed to just the ERIC ID part."""
    obj = destiny_sdk.identifiers.ERICIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.ERIC,
        identifier="https://eric.ed.gov/?id=EJ1480525",
    )

    assert obj.identifier == "EJ1480525"


def test_valid_pmid():
    identifier = 123456

    obj = destiny_sdk.identifiers.PubMedIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
        identifier=identifier,
    )
    assert obj.identifier == identifier


def test_invalid_pmid():
    with pytest.raises(ValidationError, match="Input should be a valid integer"):
        destiny_sdk.identifiers.PubMedIdentifier(
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
            identifier="abc123",
        )


def test_valid_open_alex():
    valid_open_alex = "W123456789"
    obj = destiny_sdk.identifiers.OpenAlexIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
        identifier=valid_open_alex,
    )
    assert obj.identifier == valid_open_alex


def test_open_alex_url_removed():
    identitier = "W123456789"
    valid_openalex_with_url_https = f"https://openalex.org/{identitier}"

    obj = destiny_sdk.identifiers.OpenAlexIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
        identifier=valid_openalex_with_url_https,
    )

    assert obj.identifier == identitier

    valid_openalex_with_url_http = f"http://openalex.org/{identitier}"

    obj = destiny_sdk.identifiers.OpenAlexIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
        identifier=valid_openalex_with_url_http,
    )

    assert obj.identifier == identitier


def test_invalid_open_alex():
    with pytest.raises(ValidationError, match="String should match pattern"):
        destiny_sdk.identifiers.OpenAlexIdentifier(
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
            identifier="invalid-openalex",
        )


def test_valid_other_identifier():
    obj = destiny_sdk.identifiers.OtherIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OTHER,
        identifier="custom_identifier",
        other_identifier_name="custom_type",
    )
    assert obj.other_identifier_name == "custom_type"


def test_invalid_other_identifier_missing_name():
    with pytest.raises(
        ValidationError,
        match="Field required",
    ):
        destiny_sdk.identifiers.OtherIdentifier(
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OTHER,
            identifier="custom_identifier",
        )


# IdentifierLookup Tests


class TestIdentifierLookupSerialization:
    """Test serialization of IdentifierLookup objects."""

    @pytest.mark.parametrize(
        ("identifier_type", "identifier", "other_name", "expected"),
        [
            # UUID (no type)
            (
                None,
                "550e8400-e29b-41d4-a716-446655440000",
                None,
                "550e8400-e29b-41d4-a716-446655440000",
            ),
            # Standard identifier types
            (
                destiny_sdk.identifiers.ExternalIdentifierType.DOI,
                "10.1000/xyz123",
                None,
                "doi:10.1000/xyz123",
            ),
            (
                destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
                "12345",
                None,
                "pm_id:12345",
            ),
            (
                destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
                "W123456789",
                None,
                "open_alex:W123456789",
            ),
            # Other identifier type
            (
                destiny_sdk.identifiers.ExternalIdentifierType.OTHER,
                "custom123",
                "arxiv",
                "other:arxiv:custom123",
            ),
        ],
    )
    def test_serialize(self, identifier_type, identifier, other_name, expected):
        lookup = destiny_sdk.identifiers.IdentifierLookup(
            identifier=identifier,
            identifier_type=identifier_type,
            other_identifier_name=other_name,
        )
        assert lookup.serialize() == expected

    def test_serialize_custom_delimiter(self):
        lookup = destiny_sdk.identifiers.IdentifierLookup(
            identifier="10.1000/xyz123",
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
        )
        # Default delimiter should still work
        assert lookup.serialize() == "doi:10.1000/xyz123"


class TestIdentifierLookup:
    """Test parsing of identifier lookup strings."""

    @pytest.mark.parametrize(
        (
            "input_identifier",
            "expected_lookup",
            "expected_serialization",
        ),
        [
            # UUID (no type)
            (
                uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
                destiny_sdk.identifiers.IdentifierLookup(
                    identifier="550e8400-e29b-41d4-a716-446655440000",
                    identifier_type=None,
                ),
                "550e8400-e29b-41d4-a716-446655440000",
            ),
            # DOI identifier
            (
                destiny_sdk.identifiers.DOIIdentifier(
                    identifier="10.1000/xyz123",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
                ),
                destiny_sdk.identifiers.IdentifierLookup(
                    identifier="10.1000/xyz123",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
                ),
                "doi:10.1000/xyz123",
            ),
            # PubMed identifier
            (
                destiny_sdk.identifiers.PubMedIdentifier(
                    identifier=12345,
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
                ),
                destiny_sdk.identifiers.IdentifierLookup(
                    identifier="12345",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
                ),
                "pm_id:12345",
            ),
            # OpenAlex identifier
            (
                destiny_sdk.identifiers.OpenAlexIdentifier(
                    identifier="W123456789",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
                ),
                destiny_sdk.identifiers.IdentifierLookup(
                    identifier="W123456789",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
                ),
                "open_alex:W123456789",
            ),
            # Other identifier type
            (
                destiny_sdk.identifiers.OtherIdentifier(
                    identifier="custom123",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OTHER,
                    other_identifier_name="arxiv",
                ),
                destiny_sdk.identifiers.IdentifierLookup(
                    identifier="custom123",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OTHER,
                    other_identifier_name="arxiv",
                ),
                "other:arxiv:custom123",
            ),
        ],
    )
    def test_full_round_trip(
        self, input_identifier, expected_lookup, expected_serialization
    ):
        # Step 1: Convert input identifier to IdentifierLookup using from_identifier
        lookup = destiny_sdk.identifiers.IdentifierLookup.from_identifier(
            input_identifier
        )

        # Step 2: Compare to expected IdentifierLookup
        assert lookup.identifier == expected_lookup.identifier
        assert lookup.identifier_type == expected_lookup.identifier_type
        assert lookup.other_identifier_name == expected_lookup.other_identifier_name

        # Step 3: Serialize the IdentifierLookup
        serialized = lookup.serialize()

        # Step 4: Check the serialization matches expected
        assert serialized == expected_serialization

        # Step 5: Parse it back
        parsed = destiny_sdk.identifiers.IdentifierLookup.parse(serialized)

        # Step 6: Assert parsed is the same as the lookup
        assert parsed.identifier == lookup.identifier
        assert parsed.identifier_type == lookup.identifier_type
        assert parsed.other_identifier_name == lookup.other_identifier_name

        # Step 7: Convert back to identifier using to_identifier
        result_identifier = parsed.to_identifier()

        # Step 8: Assert result is the same as input
        if isinstance(input_identifier, uuid.UUID):
            assert isinstance(result_identifier, uuid.UUID)
            assert str(result_identifier) == str(input_identifier)
        else:
            assert isinstance(result_identifier, type(input_identifier))
            assert result_identifier.identifier == input_identifier.identifier
            assert result_identifier.identifier_type == input_identifier.identifier_type
            if hasattr(input_identifier, "other_identifier_name"):
                assert (
                    result_identifier.other_identifier_name
                    == input_identifier.other_identifier_name
                )

    def test_parse_invalid_uuid(self):
        with pytest.raises(
            ValueError, match="Must be UUIDv4 if no identifier type is specified"
        ):
            destiny_sdk.identifiers.IdentifierLookup.parse("not-a-uuid")

    def test_parse_unknown_identifier_type(self):
        with pytest.raises(ValueError, match="Unknown identifier type: unknown"):
            destiny_sdk.identifiers.IdentifierLookup.parse("unknown:12345")

    def test_parse_other_missing_name(self):
        with pytest.raises(
            ValueError,
            match="Other identifier type must include other identifier name",
        ):
            destiny_sdk.identifiers.IdentifierLookup.parse("other:12345")

    def test_parse_custom_delimiter(self):
        lookup = destiny_sdk.identifiers.IdentifierLookup.parse(
            "doi|10.1000/xyz123", delimiter="|"
        )
        assert lookup.identifier == "10.1000/xyz123"
        assert (
            lookup.identifier_type == destiny_sdk.identifiers.ExternalIdentifierType.DOI
        )

    def test_parse_with_colon(self):
        lookup = destiny_sdk.identifiers.IdentifierLookup.parse(
            "other:foobar:a:b:c", delimiter=":"
        )
        assert lookup.identifier == "a:b:c"
        assert (
            lookup.identifier_type
            == destiny_sdk.identifiers.ExternalIdentifierType.OTHER
        )
        assert lookup.other_identifier_name == "foobar"
