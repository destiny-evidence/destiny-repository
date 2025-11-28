"""Tests for the EPPI parser."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from destiny_sdk.enhancements import EnhancementType
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.parsers.eppi_parser import EPPIParser


def test_parse_data():
    """Test that the parse_data method returns the expected output."""
    test_data_path = Path(__file__).parent.parent / "test_data"
    input_path = test_data_path / "eppi_report.json"
    output_path = test_data_path / "eppi_import.jsonl"

    import json

    parser = EPPIParser()
    with input_path.open() as f:
        data = json.load(f)
    references = parser.parse_data(data, robot_version="test-robot-version")

    with output_path.open() as f:
        expected_output = f.read()

    actual_output = "".join([ref.to_jsonl() + "\n" for ref in references])

    assert actual_output == expected_output


def test_parse_data_with_annotations():
    """Test that the parse_data method returns the output with annotations."""
    test_data_path = Path(__file__).parent.parent / "test_data"
    input_path = test_data_path / "eppi_report.json"
    output_path = test_data_path / "eppi_import_with_annotations.jsonl"

    import json

    parser = EPPIParser(tags=["test-tag", "another-tag"])
    with input_path.open() as f:
        data = json.load(f)
    references = parser.parse_data(data, robot_version="test-robot-version")

    with output_path.open() as f:
        expected_output = f.read()

    actual_output = "".join([ref.to_jsonl() + "\n" for ref in references])

    assert [json.loads(line) for line in actual_output.splitlines()] == [
        json.loads(line) for line in expected_output.splitlines()
    ]


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
            {
                # No identifiers
            },
        ]
    }

    parser = EPPIParser()
    references = parser.parse_data(test_data)
    assert len(references) == 3
    assert references[0].identifiers[0].identifier_type == ExternalIdentifierType.DOI
    assert (
        references[0].identifiers[1].identifier_type == ExternalIdentifierType.PROQUEST
    )
    assert references[1].identifiers[0].identifier_type == ExternalIdentifierType.ERIC
    assert len(references[2].identifiers) == 0


def test_parsing_with_raw_data_included():
    """Test that we can include raw enhancements as necessary."""
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
        raw_enhancement_metadata={"test": "metadata"},
    )

    references = parser.parse_data(test_data)
    assert len(references) == 1
    assert len(references[0].enhancements) == 1
    assert references[0].enhancements[0].content.enhancement_type == EnhancementType.RAW
    assert references[0].enhancements[0].content.data == test_data["References"][0]
    assert references[0].enhancements[0].content.metadata == {"test": "metadata"}


def test_parsing_raw_data_incorrectly_configured():
    """
    Test that we throw a runtime error if not all needed info
    for raw enhancements is provided
    """
    with pytest.raises(RuntimeError):
        EPPIParser(include_raw_data=True, source_export_date=datetime.now(tz=UTC))
