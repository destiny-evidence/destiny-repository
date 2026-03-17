"""Tests for the EEF reference deduplication script."""

from uuid import uuid4

import pytest
from deduplicate_eef_references.deduplicate_eef_references import (
    _build_decisions,
    group_references,
    parse_reference_ids,
)
from destiny_sdk.deduplication import ManualDuplicateDetermination
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.references import Reference

CANONICAL = ManualDuplicateDetermination.CANONICAL
DUPLICATE = ManualDuplicateDetermination.DUPLICATE


def _make_reference(
    *,
    identifiers: list[dict] | None = None,
) -> Reference:
    """Create a reference with a random ID."""
    return Reference(id=uuid4(), identifiers=identifiers)


def _doi(value: str) -> dict:
    return {
        "identifier": value,
        "identifier_type": ExternalIdentifierType.DOI,
    }


def _eric(value: str) -> dict:
    return {
        "identifier": value,
        "identifier_type": ExternalIdentifierType.ERIC,
    }


class TestParseReferenceIds:
    """Tests for parse_reference_ids."""

    def test_extracts_ids_between_markers(self) -> None:
        """IDs between the delimiters are returned."""
        output = (
            "some preamble\n"
            "---BEGIN_RESULTS---\n"
            "id-1\n"
            "id-2\n"
            "id-3\n"
            "---END_RESULTS---\n"
            "some epilogue\n"
        )
        assert parse_reference_ids(output) == ["id-1", "id-2", "id-3"]

    def test_strips_whitespace_and_skips_blank_lines(self) -> None:
        """Whitespace is stripped and blank lines are ignored."""
        output = (
            "---BEGIN_RESULTS---\n"
            "  id-1  \n"
            "\n"
            "  \n"
            "id-2\n"
            "---END_RESULTS---\n"
        )
        assert parse_reference_ids(output) == ["id-1", "id-2"]

    def test_empty_results(self) -> None:
        """No IDs between delimiters returns an empty list."""
        output = "---BEGIN_RESULTS---\n---END_RESULTS---\n"
        assert parse_reference_ids(output) == []

    def test_missing_begin_marker_raises(self) -> None:
        """Missing BEGIN marker raises ValueError."""
        with pytest.raises(ValueError, match="substring not found"):
            parse_reference_ids("no markers here")

    def test_missing_end_marker_raises(self) -> None:
        """Missing END marker raises ValueError."""
        with pytest.raises(ValueError, match="substring not found"):
            parse_reference_ids("---BEGIN_RESULTS---\nid-1\n")


class TestGroupReferences:
    """Tests for group_references."""

    def test_groups_by_shared_identifiers(self) -> None:
        """References with identical identifiers are grouped."""
        doi = _doi("10.1234/abc")
        ref_a = _make_reference(identifiers=[doi])
        ref_b = _make_reference(identifiers=[doi])
        ref_c = _make_reference(identifiers=[_doi("10.9999/other")])

        groups = group_references([ref_a, ref_b, ref_c])

        assert len(groups) == 1
        assert {r.id for r in groups[0]} == {ref_a.id, ref_b.id}

    def test_non_matching_refs_are_excluded(self) -> None:
        """References with different identifiers don't form groups."""
        ref_a = _make_reference(identifiers=[_doi("10.1234/abc")])
        ref_b = _make_reference(identifiers=[_eric("EJ123456")])

        assert group_references([ref_a, ref_b]) == []

    def test_multiple_identifiers_must_all_match(self) -> None:
        """Partial identifier overlap does not produce a group."""
        shared_doi = _doi("10.1234/abc")
        ref_a = _make_reference(
            identifiers=[shared_doi, _eric("EJ111111")],
        )
        ref_b = _make_reference(identifiers=[shared_doi])

        assert group_references([ref_a, ref_b]) == []


class TestBuildDecisions:
    """Tests for _build_decisions."""

    def test_single_pair(self) -> None:
        """First ref is canonical, second is duplicate."""
        canonical = _make_reference()
        duplicate = _make_reference()

        decisions = _build_decisions([canonical, duplicate])

        assert len(decisions) == 2
        assert decisions[0].reference_id == canonical.id
        assert decisions[0].duplicate_determination == CANONICAL
        assert decisions[0].canonical_reference_id is None
        assert decisions[1].reference_id == duplicate.id
        assert decisions[1].duplicate_determination == DUPLICATE
        assert decisions[1].canonical_reference_id == canonical.id

    def test_multiple_duplicates(self) -> None:
        """All non-first refs point back to the first as canonical."""
        refs = [_make_reference() for _ in range(4)]
        decisions = _build_decisions(refs)

        canonical_decisions = [
            d for d in decisions if d.duplicate_determination == CANONICAL
        ]
        duplicate_decisions = [
            d for d in decisions if d.duplicate_determination == DUPLICATE
        ]
        assert len(canonical_decisions) == 1
        assert len(duplicate_decisions) == 3
        assert all(d.canonical_reference_id == refs[0].id for d in duplicate_decisions)
