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


def test_valid_pmid():
    obj = destiny_sdk.identifiers.PubMedIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
        identifier=123456,
    )
    assert obj.identifier == 123456


def test_invalid_pmid():
    with pytest.raises(ValidationError, match="Input should be a valid integer"):
        destiny_sdk.identifiers.PubMedIdentifier(
            identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.PM_ID,
            identifier="abc123",
        )


def test_valid_open_alex():
    valid_openalex = "W123456789"
    obj = destiny_sdk.identifiers.OpenAlexIdentifier(
        identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
        identifier=valid_openalex,
    )
    assert obj.identifier == valid_openalex


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
