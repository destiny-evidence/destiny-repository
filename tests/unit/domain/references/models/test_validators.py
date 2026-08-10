from uuid import uuid7

import destiny_sdk
import pytest

from app.core.exceptions import ParseError
from app.domain.references.models.models import ExternalIdentifierType
from app.domain.references.models.validators import (
    ReferenceCreateResult,
    parse_identifier_lookup_from_string,
)


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        # Valid UUID, no type
        (
            str(uuid7()),
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
        ("not-a-uuid", {"error": "Must be UUID"}),
        ("1234-5678-90ab", {"error": "Must be UUID"}),
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


def test_exported_reference_imports_without_rewriting():
    """A JSONL line straight from an export endpoint parses, ignoring its id."""
    reference_id = uuid7()
    exported = destiny_sdk.references.Reference(
        id=reference_id,
        identifiers=[{"identifier_type": "doi", "identifier": "10.1000/xyz"}],
        enhancements=[
            destiny_sdk.enhancements.Enhancement(
                id=uuid7(),
                reference_id=reference_id,
                source="test-source",
                visibility="public",
                content={
                    "enhancement_type": "abstract",
                    "process": "closed_api",
                    "abstract": "hello",
                },
            )
        ],
    ).to_jsonl()

    result = ReferenceCreateResult.from_raw(exported, 1)

    assert result.errors == []
    assert result.reference is not None
    assert result.reference.identifiers[0].identifier == "10.1000/xyz"
    assert result.reference.enhancements[0].source == "test-source"
    # ReferenceFileInput carries no id, so the exported one cannot be adopted.
    assert "id" not in result.reference.model_dump()


def test_unknown_top_level_field_is_still_rejected():
    """Accepting `id` must not open the schema up to arbitrary fields."""
    result = ReferenceCreateResult.from_raw(
        '{"identifiers": [{"identifier_type": "doi", "identifier": "10.1/a"}],'
        ' "nonsense": 1}',
        1,
    )

    assert result.reference is None
    assert "nonsense" in result.error_str
