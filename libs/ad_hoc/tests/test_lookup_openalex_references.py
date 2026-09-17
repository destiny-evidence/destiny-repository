"""Tests for the OpenAlex reference lookup script."""

from pathlib import Path
from uuid import uuid4

import pytest
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.references import Reference
from lookup_openalex_references.lookup_openalex_references import (
    load_work_ids,
    normalise_work_id,
    unresolved_work_ids,
)

WORK = "W3121659249"


def _reference(*work_ids: str) -> Reference:
    """Create a reference carrying the given OpenAlex works."""
    return Reference(
        id=uuid4(),
        identifiers=[
            {
                "identifier": work_id,
                "identifier_type": ExternalIdentifierType.OPEN_ALEX,
            }
            for work_id in work_ids
        ],
    )


class TestNormaliseWorkId:
    """Tests for normalise_work_id."""

    def test_bare_work_id_is_unchanged(self) -> None:
        """The form the repository stores passes through."""
        assert normalise_work_id(WORK) == WORK

    def test_prefixed_identifier_is_stripped(self) -> None:
        """The lookup-parameter form is accepted as input."""
        assert normalise_work_id(f"open_alex:{WORK}") == WORK

    def test_url_form_is_reduced_to_the_work_id(self) -> None:
        """OpenAlex exports carry the full URL."""
        assert normalise_work_id(f"https://openalex.org/{WORK}") == WORK

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """Input files are read line by line."""
        assert normalise_work_id(f"  {WORK}\n") == WORK

    def test_rejects_an_identifier_that_is_not_an_openalex_work(self) -> None:
        """A DOI would resolve to nothing and report no error."""
        with pytest.raises(ValueError, match="not an OpenAlex work"):
            normalise_work_id("10.1234/abc")


class TestLoadWorkIds:
    """Tests for load_work_ids."""

    def test_reads_bare_and_prefixed_files_together(self, tmp_path: Path) -> None:
        """The two input forms in use are both accepted."""
        bare = tmp_path / "bare.txt"
        bare.write_text("W1\nW2\n")
        prefixed = tmp_path / "prefixed.txt"
        prefixed.write_text("open_alex:W3\n")

        assert load_work_ids([bare, prefixed]) == ["W1", "W2", "W3"]

    def test_deduplicates_across_files_preserving_order(self, tmp_path: Path) -> None:
        """A work named twice is looked up once."""
        first = tmp_path / "first.txt"
        first.write_text("W1\nW2\n")
        second = tmp_path / "second.txt"
        second.write_text("open_alex:W2\nW3\n")

        assert load_work_ids([first, second]) == ["W1", "W2", "W3"]

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        """Hand-maintained files carry stray blank lines."""
        path = tmp_path / "wids.txt"
        path.write_text("W1\n\n  \nW2\n")

        assert load_work_ids([path]) == ["W1", "W2"]


class TestUnresolvedWorkIds:
    """Tests for unresolved_work_ids."""

    def test_reports_works_with_no_reference(self) -> None:
        """A partial pull is the failure this exists to surface."""
        assert unresolved_work_ids(["W1", "W2"], [_reference("W1")]) == ["W2"]

    def test_returns_empty_when_every_work_resolved(self) -> None:
        """A complete pull reports nothing."""
        assert unresolved_work_ids(["W1"], [_reference("W1")]) == []

    def test_a_reference_without_identifiers_resolves_nothing(self) -> None:
        """The model leaves identifiers unset, so iterating it needs a guard."""
        assert unresolved_work_ids(["W1"], [Reference(id=uuid4())]) == ["W1"]

    def test_ignores_identifiers_that_are_not_openalex(self) -> None:
        """A reference carries other identifier types alongside the work."""
        reference = Reference(
            id=uuid4(),
            identifiers=[
                {"identifier": "10.1234/abc", "identifier_type": "doi"},
                {"identifier": "W1", "identifier_type": "open_alex"},
            ],
        )

        assert unresolved_work_ids(["W1"], [reference]) == []
