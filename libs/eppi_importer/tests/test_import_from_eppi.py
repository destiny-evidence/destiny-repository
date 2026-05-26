"""Tests for the EPPI importer CLI."""

import json
import sys
from pathlib import Path

import pytest

from libs.eppi_importer import import_from_eppi


def _bibliographic_title(record: dict) -> str | None:
    for enh in record.get("enhancements", []):
        content = enh.get("content") or {}
        if content.get("enhancement_type") == "bibliographic":
            return content.get("title")
    return None


@pytest.fixture
def utf8_eppi_export(tmp_path: Path) -> Path:
    """
    Build an EPPI export written as UTF-8 with U+2019 in the title.

    Mirrors the byte pattern at offset 1895095 in eef_export-2025-12-03 (the
    EEF EPPI export that triggered the mojibake bug).
    """
    data = {
        "CodeSets": [],
        "References": [
            {
                "Title": "Teachers’ training, class size and students’ outcomes",  # noqa: RUF001
                "DOI": "10.1111/j.1468-0297.2008.02247.x",
            }
        ],
    }
    path = tmp_path / "eppi_utf8.json"
    path.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return path


def test_cli_default_codec_preserves_utf8_apostrophe(
    utf8_eppi_export: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""
    The default --input-codec must decode UTF-8 EPPI exports correctly.

    Regression for the EEF 2025-12-03 mojibake bug: latin-1 was the default,
    so \xe2\x80\x99 (U+2019) decoded into U+00E2 + U+0080 + U+0099 (mojibake)
    instead of a clean right single quotation mark.
    """
    output_path = tmp_path / "out.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_from_eppi",
            "--input",
            str(utf8_eppi_export),
            "--output",
            str(output_path),
            "--source",
            "test-eef-utf8",
        ],
    )

    import_from_eppi.main()

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "Expected one reference in output"
    record = json.loads(lines[0])

    title = _bibliographic_title(record)
    assert title is not None, "Expected a bibliographic enhancement with a title"
    assert "’" in title, f"Expected U+2019 in title, got: {title!r}"  # noqa: RUF001
    # Mojibake codepoints from latin-1 misdecode of \xe2\x80\x99:
    assert "â" not in title, f"Latin-1 mojibake leaked into title: {title!r}"
    assert "\u0080" not in title, f"C1 control char in title: {title!r}"
    assert "\u0099" not in title, f"C1 control char in title: {title!r}"
