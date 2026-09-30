"""Tests for the OpenAlex reference lookup utility."""

from pathlib import Path
from uuid import uuid4

import pytest
from destiny_sdk.enhancements import (
    AbstractContentEnhancement,
    AbstractProcessType,
    Enhancement,
)
from destiny_sdk.identifiers import OpenAlexIdentifier
from destiny_sdk.references import Reference

from cli.lookup_openalex_references import (
    argument_parser,
    fetch_references,
    load_work_ids,
    normalise_work_id,
    unresolved_work_ids,
    write_references,
)

WORK = "W3121659249"


def _reference(*work_ids: str) -> Reference:
    """Create a reference carrying the given OpenAlex works."""
    return Reference(
        id=uuid4(),
        identifiers=[OpenAlexIdentifier(identifier=work_id) for work_id in work_ids],
    )


class TestNormaliseWorkId:
    """Tests for normalise_work_id."""

    def test_bare_work_id_is_unchanged(self) -> None:
        """The form the repository stores passes through."""
        assert normalise_work_id(WORK) == WORK

    def test_prefixed_identifier_is_stripped(self) -> None:
        """The lookup-parameter form is accepted as input."""
        assert normalise_work_id(f"open_alex:{WORK}") == WORK

    @pytest.mark.parametrize(
        "url",
        [
            f"https://openalex.org/{WORK}",
            f"http://openalex.org/{WORK}",
            f"https://openalex.org/works/{WORK}",
        ],
    )
    def test_url_forms_are_reduced_to_the_work_id(self, url: str) -> None:
        """OpenAlex exports and pasted links carry the work as a URL."""
        assert normalise_work_id(url) == WORK

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

    def test_deduplicates_across_files(self, tmp_path: Path) -> None:
        """A work named twice is looked up once."""
        first = tmp_path / "first.txt"
        first.write_text("W1\nW2\n")
        second = tmp_path / "second.txt"
        second.write_text("open_alex:W2\nW3\n")

        assert load_work_ids([first, second]) == ["W1", "W2", "W3"]

    def test_is_sorted_so_reruns_chunk_identically(self, tmp_path: Path) -> None:
        """Input order carries no meaning, and a set's order varies between runs."""
        path = tmp_path / "wids.txt"
        path.write_text("W3\nW1\nW2\n")

        assert load_work_ids([path]) == ["W1", "W2", "W3"]

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        """Hand-maintained files carry stray blank lines."""
        path = tmp_path / "wids.txt"
        path.write_text("W1\n\n  \nW2\n")

        assert load_work_ids([path]) == ["W1", "W2"]

    def test_reads_a_named_csv_column(self, tmp_path: Path) -> None:
        """Match files carry the work as a URL beside quoted multi-line fields."""
        path = tmp_path / "matches.csv"
        path.write_text(
            "PaperID,openalex_id,supplied_title\n"
            '1,https://openalex.org/W1,"Title split\nacross lines"\n'
            "2,,Unmatched\n"
            "3,https://openalex.org/W1,Delivered twice\n"
            "4,https://openalex.org/W2,Plain\n",
            encoding="utf-8-sig",
        )

        assert load_work_ids([path], column="openalex_id") == ["W1", "W2"]

    def test_rejects_a_column_the_file_lacks(self, tmp_path: Path) -> None:
        """A misspelt column would otherwise read as a file with no works."""
        path = tmp_path / "matches.csv"
        path.write_text("PaperID,openalex_id\n1,W1\n")

        with pytest.raises(ValueError, match="no column .openalex."):
            load_work_ids([path], column="openalex")


class _RecordingClient:
    """Stands in for OAuthClient, recording each lookup it is asked for."""

    def __init__(self) -> None:
        self.lookups: list[list[str]] = []

    def lookup(self, identifiers: list) -> list[Reference]:
        lookup = [str(identifier) for identifier in identifiers]
        self.lookups.append(lookup)
        return [_reference(value.removeprefix("open_alex:")) for value in lookup]


def test_fetch_references_chunks_at_the_lookup_limit() -> None:
    """The API rejects more than 100 identifiers in one lookup."""
    client = _RecordingClient()
    work_ids = [f"W{n}" for n in range(150)]

    references = fetch_references(client, work_ids)  # type: ignore[arg-type]

    assert [len(lookup) for lookup in client.lookups] == [100, 50]
    assert client.lookups[0][0] == "open_alex:W0"
    assert len(references) == 150


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


def test_identifier_file_is_repeatable(tmp_path: Path) -> None:
    """Works come from several hand-maintained files in one run."""
    args = argument_parser().parse_args(
        [
            "--identifier-file",
            "first.txt",
            "--identifier-file",
            "second.txt",
            "--output",
            str(tmp_path / "lookup.jsonl"),
        ]
    )

    assert args.identifier_files == [Path("first.txt"), Path("second.txt")]


def test_unicode_line_separators_stay_on_one_line(tmp_path: Path) -> None:
    """Readers split the file with str.splitlines, which breaks on U+2028/U+2029."""
    reference = _reference(WORK)
    reference.enhancements = [
        Enhancement(
            reference_id=reference.id,
            source="test",
            visibility="public",
            content=AbstractContentEnhancement(
                abstract="first\u2028second\u2029third",
                process=AbstractProcessType.OTHER,
            ),
        )
    ]
    following = _reference("W1")
    output = tmp_path / "lookup.jsonl"

    write_references(output, [reference, following])

    lines = output.read_text(encoding="utf-8").splitlines()
    assert [Reference.model_validate_json(line).id for line in lines] == [
        reference.id,
        following.id,
    ]
