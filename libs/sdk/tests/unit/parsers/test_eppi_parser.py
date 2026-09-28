"""Tests for the EPPI parser."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from destiny_sdk.enhancements import EnhancementType
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.parsers.eppi_parser import EPPIParser
from destiny_sdk.parsers.exceptions import ReferenceIdNotFoundError

EPPI_EXPORT_REFERENCE_ID = UUID("019f880e-2c39-7138-a387-221808f02d98")


@pytest.fixture
def parser():
    """A raw enhancements parser."""
    return EPPIParser(
        include_raw_data=True,
        source_export_date=datetime.fromisoformat("2023-12-02T16:30:00"),
        data_description="A full reference as exported from EPPI",
        raw_enhancement_excludes=["Abstract"],
    )


def test_parse_references():
    """Test that the parse_references method returns the expected output."""
    test_data_path = Path(__file__).parent.parent / "test_data"
    input_path = test_data_path / "eppi_report.json"
    output_path = test_data_path / "eppi_import.jsonl"

    parser = EPPIParser()
    with input_path.open() as f:
        data = json.load(f)
    references, _ = parser.parse_references(
        data, source="test-source", robot_version="test-robot-version"
    )

    with output_path.open() as f:
        expected_output = f.read()

    actual_output = "".join([ref.to_jsonl() + "\n" for ref in references])

    assert actual_output == expected_output


def test_parse_references_with_annotations():
    """Test that the parse_references method returns the output with annotations."""
    test_data_path = Path(__file__).parent.parent / "test_data"
    input_path = test_data_path / "eppi_report.json"
    output_path = test_data_path / "eppi_import_with_annotations.jsonl"

    parser = EPPIParser(
        tags=["test-scheme/test-label", "another-scheme/another-label@0.9"]
    )

    # Override the parser_source so the test isn't dependent on
    # parser versioning
    parser.parser_source = "test-source"

    with input_path.open() as f:
        data = json.load(f)
    references, _ = parser.parse_references(
        data, source="test-source", robot_version="test-robot-version"
    )

    with output_path.open() as f:
        expected_output = f.read()

    actual_output = "".join([ref.to_jsonl() + "\n" for ref in references])

    assert [json.loads(line) for line in actual_output.splitlines()] == [
        json.loads(line) for line in expected_output.splitlines()
    ]


def test_parse_references_with_raw(parser):
    test_data_path = Path(__file__).parent.parent / "test_data"
    input_path = test_data_path / "eppi_report.json"
    output_path = test_data_path / "eppi_import_with_raw.jsonl"

    with input_path.open() as f:
        data = json.load(f)
    references, _ = parser.parse_references(
        data, source="test-source", robot_version="test-robot-version"
    )

    with output_path.open() as f:
        expected_output = f.read()

    actual_output = "".join([ref.to_jsonl() + "\n" for ref in references])

    assert actual_output == expected_output


def test_parsing_identifiers():
    """Test that we can parse all expected identifiers."""
    test_data = {
        "References": [
            {
                # A doi identifier and a proquest identifier
                "DOI": "https://doi.org/10.1080/00220973.1978.11011636",
                "URL": "https://www.proquest.com/docview/1299989139",
            },
            {
                # An eric identifier
                "URL": "https://eric.ed.gov/?id=ED581143"
            },
        ]
    }

    parser = EPPIParser()
    references, _ = parser.parse_references(test_data)
    assert len(references) == 2
    assert references[0].identifiers[0].identifier_type == ExternalIdentifierType.DOI
    assert (
        references[0].identifiers[1].identifier_type == ExternalIdentifierType.PRO_QUEST
    )
    assert references[1].identifiers[0].identifier_type == ExternalIdentifierType.ERIC


def test_parsing_item_id_as_other_identifier():
    """Test that the ItemId is parsed as an OtherIdentifier first when enabled."""
    test_data = {
        "References": [
            {
                "ItemId": 109014171,
                "DOI": "10.1080/00220973.1978.11011636",
            },
        ]
    }

    parser = EPPIParser(include_eppi_id=True)
    references, _ = parser.parse_references(test_data)
    assert len(references) == 1
    identifiers = references[0].identifiers
    assert identifiers[0].identifier_type == ExternalIdentifierType.OTHER
    assert identifiers[0].identifier == "109014171"
    assert identifiers[0].other_identifier_name == "EPPI ItemId"
    assert identifiers[1].identifier_type == ExternalIdentifierType.DOI


def test_item_id_not_included_by_default():
    """Test that the ItemId is not parsed unless include_eppi_id is set."""
    test_data = {
        "References": [
            {
                "ItemId": 109014171,
                "DOI": "10.1080/00220973.1978.11011636",
            },
        ]
    }

    parser = EPPIParser()
    references, _ = parser.parse_references(test_data)
    assert len(references) == 1
    identifiers = references[0].identifiers
    assert len(identifiers) == 1
    assert identifiers[0].identifier_type == ExternalIdentifierType.DOI


def test_parsing_doi_from_url():
    """Test that a DOI can be parsed from a doi.org URL."""
    test_data = {
        "References": [
            {
                # A DOI provided only as a URL
                "URL": "https://doi.org/10.1080/00220973.1978.11011636",
            },
            {
                # A DOI provided only as a dx.doi.org URL
                "URL": "http://dx.doi.org/10.1080/00220973.1978.11011636",
            },
        ]
    }

    parser = EPPIParser()
    references, _ = parser.parse_references(test_data)
    assert len(references) == 2
    for reference in references:
        assert len(reference.identifiers) == 1
        assert reference.identifiers[0].identifier_type == ExternalIdentifierType.DOI
        assert reference.identifiers[0].identifier == "10.1080/00220973.1978.11011636"


def test_duplicate_doi_in_field_and_url_is_deduplicated():
    """Test that a DOI present in both the DOI field and URL is only added once."""
    test_data = {
        "References": [
            {
                "DOI": "10.1080/00220973.1978.11011636",
                "URL": "https://doi.org/10.1080/00220973.1978.11011636",
            },
        ]
    }

    parser = EPPIParser()
    references, _ = parser.parse_references(test_data)
    assert len(references) == 1
    assert len(references[0].identifiers) == 1
    assert references[0].identifiers[0].identifier_type == ExternalIdentifierType.DOI


def test_reference_with_no_identifiers_is_not_included():
    """Test that we do not return references with no identifiers."""
    test_data = {
        "References": [
            {
                "Stuff": "that isn't",
                "An": "identifier",
            },
        ]
    }

    parser = EPPIParser()
    references, failed_refs = parser.parse_references(test_data)
    assert len(references) == 0
    assert len(failed_refs) == 1


def test_parsing_with_raw_data_included():
    """Test that we can include raw enhancements as necessary."""
    test_data = {
        "CodeSets": [
            {"SetId": 83429},
        ],
        "References": [
            {
                "ShortTitle": "Husain (2016)",
                "DateCreated": "19/11/2018",
                "DOI": "https://doi.org/10.1080/00220973.1978.11011636",
                "Issue": "July",
            }
        ],
    }

    parser = EPPIParser(
        include_raw_data=True,
        source_export_date=datetime.now(tz=UTC),
        data_description="EPPI test data",
    )

    references, failed_refs = parser.parse_references(test_data)
    assert len(references) == 1
    assert len(references[0].enhancements) == 1
    assert references[0].enhancements[0].content.enhancement_type == EnhancementType.RAW
    assert references[0].enhancements[0].content.data == test_data["References"][0]
    assert references[0].enhancements[0].content.metadata == {
        "codeset_ids": [test_data.get("CodeSets")[0].get("SetId")]
    }

    assert len(failed_refs) == 0


def test_parsing_with_raw_data_no_codesets():
    """Test that we can parse references with no CodeSets included."""
    test_data = {
        "References": [
            {
                "ShortTitle": "Husain (2016)",
                "DateCreated": "19/11/2018",
                "DOI": "https://doi.org/10.1080/00220973.1978.11011636",
                "Issue": "July",
            }
        ]
    }

    parser = EPPIParser(
        include_raw_data=True,
        source_export_date=datetime.now(tz=UTC),
        data_description="EPPI test data",
    )
    references, _ = parser.parse_references(test_data)

    assert len(references) == 1
    assert references[0].enhancements[0].content.metadata.get("codeset_ids") == []


def test_raw_enhancements_exclude_fields():
    """Test that we can exclude fields from raw enhancements as necessary."""
    test_data = {
        # Contains info for bibliographic, abstract, and raw enhancements.
        "References": [
            {
                "Title": "Tuatara Extra Eye",
                "Abstract": "They've got an extra one on top of their head it's true.",
                "DateCreated": "19/11/2011",
                "DOI": "https://doi.org/10.1080/00220973.1978.11011636",
                "Issue": "July",
            }
        ]
    }

    parser = EPPIParser(
        include_raw_data=True,
        source_export_date=datetime.now(tz=UTC),
        data_description="EPPI test data",
        raw_enhancement_excludes=["Abstract", "Issue"],
    )

    references, _ = parser.parse_references(test_data)
    assert len(references) == 1
    assert len(references[0].enhancements) == 3

    raw_enhancement = references[0].enhancements[2]
    assert raw_enhancement.content.enhancement_type == EnhancementType.RAW
    assert not raw_enhancement.content.data.get("Abstract")
    assert not raw_enhancement.content.data.get("Issue")
    assert raw_enhancement.content.data.get("Title") == "Tuatara Extra Eye"


def test_parsing_raw_data_incorrectly_configured():
    """
    Test that we throw a runtime error if not all needed info
    for raw enhancements is provided
    """
    with pytest.raises(RuntimeError):
        EPPIParser(include_raw_data=True, source_export_date=datetime.now(tz=UTC))


def test_parse_enhancements(parser):
    """Test that an EPPI export is parsed into one raw enhancement per reference."""
    input_path = Path(__file__).parent.parent / "test_data" / "eppi_export.json"
    with input_path.open() as f:
        data = json.load(f)

    enhancements = parser.parse_enhancements(
        data, source="test-source", robot_version="test-robot-version"
    )

    assert len(enhancements) == 1
    enhancement = enhancements[0]
    assert enhancement.reference_id == EPPI_EXPORT_REFERENCE_ID
    assert enhancement.source == "test-source"
    assert enhancement.robot_version == "test-robot-version"
    assert enhancement.content.enhancement_type == EnhancementType.RAW
    assert enhancement.content.metadata == {"codeset_ids": [96392, 99762, 391604]}
    assert not enhancement.content.data.get("Abstract")
    assert len(enhancement.content.data["Codes"]) == 3
    assert enhancement.content.data["Outcomes"][0]["OutcomeId"] == 138630


def test_parse_enhancements_requires_raw_data():
    """Test that enhancements can't be parsed without raw data configured."""
    with pytest.raises(RuntimeError):
        EPPIParser().parse_enhancements({"References": []}, source="test-source")


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://doi.org/10.1080/00220973.1978.11011636",
        # Truncated to less than a uuid's length
        "https://data.evidence-repository.org/esea/references/019f880e-2c39-7138",
        # A syntactically valid uuid, but neither a uuid4 nor a uuid7
        "https://data.evidence-repository.org/esea/references/"
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_parse_enhancements_without_a_reference_id(parser, url):
    """Test that a reference we can't attach to rejects the whole export."""
    test_data = {"References": [{"ItemId": 116012899, "URL": url}]}

    with pytest.raises(ReferenceIdNotFoundError) as exc_info:
        parser.parse_enhancements(test_data, source="test-source")

    assert "ItemId 116012899" in exc_info.value.detail


def test_parse_enhancements_reports_every_unidentified_reference(parser):
    """Test that all references without a reference id are reported at once."""
    test_data = {
        "References": [
            {"ItemId": 1, "URL": ""},
            {
                "ItemId": 2,
                "URL": "https://data.evidence-repository.org/esea/references/"
                f"{EPPI_EXPORT_REFERENCE_ID}/",
            },
            {"ItemId": 3, "URL": "https://eric.ed.gov/?id=ED581143"},
        ]
    }

    with pytest.raises(ReferenceIdNotFoundError) as exc_info:
        parser.parse_enhancements(test_data, source="test-source")

    assert "ItemId 1" in exc_info.value.detail
    assert "ItemId 3" in exc_info.value.detail
    assert "ItemId 2" not in exc_info.value.detail
