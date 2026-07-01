"""Unit tests for the RisRecord model and its RIS rendering."""

import datetime

import pytest

from app.domain.references.models.ris import RisRecord, RisType


def test_render_full_record():
    """A fully populated record renders every tag, TY first and ER last."""
    record = RisRecord(
        reference_type=RisType.JOURNAL,
        title="A Title",
        authors=["Jit Mark", "Hayes Richard"],
        publication_year=2020,
        publication_date=datetime.date(2020, 4, 2),
        journal="The Journal",
        volume="12",
        issue="3",
        start_page="100",
        end_page="110",
        publisher="A Publisher",
        issns=["1234-5678", "8765-4321"],
        abstract="An abstract.",
        doi="10.1000/abc",
        accession="999",
        database="PubMed",
        pdf_url="https://example.org/a.pdf",
        urls=["https://example.org/a"],
    )

    lines = record.render(exclude=()).split("\n")

    assert lines[0] == "TY  - JOUR"
    assert lines[-1] == "ER  - "
    # Authors and ISSNs repeat one tag per value, verbatim (no reordering).
    assert lines.count("AU  - Jit Mark") == 1
    assert "AU  - Hayes Richard" in lines
    assert "SN  - 1234-5678" in lines
    assert "SN  - 8765-4321" in lines
    assert "TI  - A Title" in lines
    assert "PY  - 2020" in lines
    assert "DA  - 2020/04/02" in lines
    assert "T2  - The Journal" in lines
    assert "VL  - 12" in lines
    assert "IS  - 3" in lines
    assert "SP  - 100" in lines
    assert "EP  - 110" in lines
    assert "PB  - A Publisher" in lines
    assert "DO  - 10.1000/abc" in lines
    assert "AN  - 999" in lines
    assert "DB  - PubMed" in lines
    assert "UR  - https://example.org/a" in lines
    assert "L1  - https://example.org/a.pdf" in lines
    assert "AB  - An abstract." in lines


def test_render_minimal_record_only_emits_present_tags():
    """Absent fields are skipped; only TY, the set field, and ER are emitted."""
    record = RisRecord(reference_type=RisType.GENERIC, title="Only a title")

    assert record.render() == "TY  - GEN\nTI  - Only a title\nER  - "


def test_render_flattens_internal_newlines():
    """Newlines inside a value are flattened so one tag stays on one line."""
    record = RisRecord(reference_type=RisType.JOURNAL, abstract="Line one\nline two")

    assert record.render(exclude=()).split("\n") == [
        "TY  - JOUR",
        "AB  - Line one line two",
        "ER  - ",
    ]


def test_render_excludes_abstract_by_default():
    """The abstract is omitted by default and included only when not excluded."""
    record = RisRecord(reference_type=RisType.JOURNAL, abstract="An abstract.")

    assert "AB  - " not in record.render()
    assert "AB  - An abstract." in record.render(exclude=()).split("\n")
    assert "AB  - " not in record.render(exclude={"abstract"})


def test_render_rejects_unknown_excluded_field():
    """Excluding a field that doesn't exist is a loud error, not a silent no-op."""
    record = RisRecord(reference_type=RisType.JOURNAL)

    with pytest.raises(ValueError, match="abstrct"):
        record.render(exclude={"abstrct"})


def test_render_has_no_trailing_newline():
    """The caller joins records with newlines, so a record has no trailing one."""
    rendered = RisRecord(reference_type=RisType.JOURNAL, title="T").render()

    assert not rendered.endswith("\n")
    assert rendered.endswith("ER  - ")
