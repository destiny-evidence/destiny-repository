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
