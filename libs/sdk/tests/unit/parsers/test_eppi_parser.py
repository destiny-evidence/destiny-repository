"""Tests for the EPPI parser."""

from pathlib import Path

from destiny_sdk.parsers.eppi_parser import parse_file


def test_parse_file():
    """Test that the parse_file function returns the expected output."""
    test_data_path = Path(__file__).parent.parent / "test_data"
    input_path = test_data_path / "eppi_report.json"
    output_path = test_data_path / "eppi_import.jsonl"

    references = parse_file(input_path)

    with output_path.open() as f:
        expected_output = f.read()

    actual_output = "".join([ref.to_jsonl() + "\n" for ref in references])

    assert actual_output == expected_output
