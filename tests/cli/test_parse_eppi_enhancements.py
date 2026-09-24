"""Tests for the EPPI enhancement parser's verification and output."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

import httpx
import pytest
from destiny_sdk.enhancements import Enhancement, EnhancementType, RawEnhancement
from destiny_sdk.parsers.exceptions import ReferenceIdNotFoundError
from destiny_sdk.visibility import Visibility
from pytest_httpx import HTTPXMock

from app.core.config import Environment
from cli.client import get_client
from cli.parse_eppi_enhancements import (
    argument_parser,
    parse_eppi_enhancements,
    verify_references,
)

REFERENCE_ID = UUID("019f880e-2c39-7138-a387-221808f02d98")
REFERENCE_URL = f"https://data.evidence-repository.org/esea/references/{REFERENCE_ID}"
EARLIER_REFERENCE_ID = UUID("019f880d-1b28-7027-9276-110707e01c87")
EARLIER_REFERENCE_URL = (
    f"https://data.evidence-repository.org/esea/references/{EARLIER_REFERENCE_ID}"
)
SOURCE = "eef-eppi-review"


def _export(tmp_path: Path, *references: dict) -> Path:
    """Write an EPPI export holding the given references."""
    path = tmp_path / "eppi_export.json"
    path.write_bytes(
        json.dumps(
            {"CodeSets": [{"SetId": 96392}], "References": list(references)},
            ensure_ascii=False,
        ).encode("utf-8")
    )
    return path


def _raw_enhancement(reference_id: UUID, title: str | None = None) -> Enhancement:
    """Build a parsed enhancement, as ``parse_enhancements`` would return it."""
    data: dict = {"ItemId": 116012899}
    if title:
        data["Title"] = title
    return Enhancement(
        reference_id=reference_id,
        source=SOURCE,
        visibility=Visibility.PUBLIC,
        content=RawEnhancement(
            source_export_date=datetime(2026, 9, 16, tzinfo=UTC),
            description="EEF additional coding request",
            data=data,
        ),
    )


def _reference_response(reference_id: UUID, *titles: str) -> dict:
    """Build the repository's view of a reference, one enhancement per title."""
    return {
        "id": str(reference_id),
        "visibility": "public",
        "enhancements": [
            {
                "reference_id": str(reference_id),
                "source": "open-alex",
                "visibility": "public",
                "content": {"enhancement_type": "bibliographic", "title": title},
            }
            for title in titles
        ],
    }


def _args(export: Path, output: Path, *extra: str) -> argparse.Namespace:
    """Build the arguments for a run against the given export."""
    return argument_parser().parse_args(
        [
            "--input",
            str(export),
            "--output",
            str(output),
            "--source",
            SOURCE,
            "--description",
            "EEF additional coding request",
            "--source-export-date",
            "2026-09-16",
            *extra,
        ]
    )


def test_enhancement_is_written_for_each_verified_reference(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """A reference the repository knows is written out as a raw enhancement."""
    export = _export(
        tmp_path,
        {
            "ItemId": 116012899,
            "URL": REFERENCE_URL,
            "Abstract": "Excluded from the raw enhancement.",
            "Codes": [{"AttributeId": 5215229}],
        },
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json={"id": str(REFERENCE_ID), "visibility": "public"},
    )

    parse_eppi_enhancements(_args(export, output))

    enhancement = Enhancement.from_jsonl(output.read_text().splitlines()[0])
    assert enhancement.reference_id == REFERENCE_ID
    assert enhancement.source == SOURCE
    assert enhancement.content.enhancement_type == EnhancementType.RAW
    assert enhancement.content.metadata == {"codeset_ids": [96392]}
    assert not enhancement.content.data.get("Abstract")


def test_reference_not_in_the_repository_writes_nothing(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Enhancements are only written once every reference is known to exist."""
    export = _export(tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL})
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        status_code=404,
    )

    with pytest.raises(ValueError, match="not in the repository"):
        parse_eppi_enhancements(_args(export, output))

    assert not output.exists()


def test_reference_without_an_id_is_never_verified(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """An export we can't attach fails before any reference is looked up."""
    export = _export(tmp_path, {"ItemId": 116012899, "URL": "https://eppi.example/1"})
    output = tmp_path / "enhancements.jsonl"

    with pytest.raises(ReferenceIdNotFoundError, match="ItemId 116012899"):
        parse_eppi_enhancements(_args(export, output))

    assert not httpx_mock.get_requests()
    assert not output.exists()


def test_duplicate_references_are_reported_before_verification(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Every reference enhanced more than once is named, in the export's order."""
    export = _export(
        tmp_path,
        {"ItemId": 116012899, "URL": REFERENCE_URL},
        {"ItemId": 116012900, "URL": EARLIER_REFERENCE_URL},
        {"ItemId": 116012901, "URL": EARLIER_REFERENCE_URL},
        {"ItemId": 116012902, "URL": REFERENCE_URL},
        {"ItemId": 116012903, "URL": REFERENCE_URL},
    )
    output = tmp_path / "enhancements.jsonl"

    with pytest.raises(ValueError, match="Duplicate enhancements") as exc_info:
        parse_eppi_enhancements(_args(export, output))

    assert str(exc_info.value).endswith(
        "2 reference id(s) are enhanced more than once: "
        f"{REFERENCE_ID} (3 enhancements), "
        f"{EARLIER_REFERENCE_ID} (2 enhancements)."
    )
    assert not httpx_mock.get_requests()
    assert not output.exists()


TITLE = "An Evaluation of the Early Childhood Care and Development Programme in Bhutan"


def test_title_differing_from_the_repository_warns_without_failing(
    tmp_path: Path, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A title the repository disagrees with is reported, and still written out."""
    export = _export(
        tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL, "Title": TITLE}
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json=_reference_response(REFERENCE_ID, "A Study of Something Else Entirely"),
    )

    parse_eppi_enhancements(_args(export, output))

    printed = capsys.readouterr().out
    assert "WARNING: 1 reference(s) have a title differing" in printed
    assert str(REFERENCE_ID) in printed
    assert "A Study of Something Else Entirely" in printed
    assert len(output.read_text().splitlines()) == 1


def test_title_differing_only_in_case_and_whitespace_does_not_warn(
    tmp_path: Path, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Incidental formatting differences are not worth warning about."""
    export = _export(
        tmp_path,
        {"ItemId": 116012899, "URL": REFERENCE_URL, "Title": f"  {TITLE.upper()}  "},
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json=_reference_response(REFERENCE_ID, TITLE.replace(" the ", "\n the  ")),
    )

    parse_eppi_enhancements(_args(export, output))

    assert "WARNING" not in capsys.readouterr().out


def test_matching_one_of_several_repository_titles_does_not_warn(
    tmp_path: Path, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reference titled by several sources matches if any one of them agrees."""
    export = _export(
        tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL, "Title": TITLE}
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json=_reference_response(REFERENCE_ID, "An Evaluation of the ECCD", TITLE),
    )

    parse_eppi_enhancements(_args(export, output))

    assert "WARNING" not in capsys.readouterr().out


def test_reference_the_repository_holds_no_title_for_is_not_a_mismatch(
    tmp_path: Path, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing to compare against is counted, not warned about."""
    export = _export(
        tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL, "Title": TITLE}
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json=_reference_response(REFERENCE_ID),
    )

    parse_eppi_enhancements(_args(export, output))

    printed = capsys.readouterr().out
    assert "WARNING" not in printed
    assert "1 reference(s) had no title to compare." in printed


def test_excluding_the_title_from_the_raw_enhancement_leaves_nothing_to_compare(
    tmp_path: Path, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A title kept out of the enhancement is reported rather than silently skipped."""
    export = _export(
        tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL, "Title": TITLE}
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json=_reference_response(REFERENCE_ID, "A Study of Something Else Entirely"),
    )

    parse_eppi_enhancements(_args(export, output, "--exclude-from-raw", "Title"))

    printed = capsys.readouterr().out
    assert "WARNING" not in printed
    assert "1 reference(s) had no title to compare." in printed


def test_skip_verification_asks_the_repository_nothing(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """A disconnected run writes the enhancements without checking them."""
    export = _export(tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL})
    output = tmp_path / "enhancements.jsonl"

    parse_eppi_enhancements(_args(export, output, "--skip-verification"))

    assert not httpx_mock.get_requests()
    assert len(output.read_text().splitlines()) == 1


def test_unauthorized_verification_is_not_reported_as_a_missing_reference(
    httpx_mock: HTTPXMock,
) -> None:
    """A rejected request says so, rather than claiming the reference is absent."""
    reference_id = uuid7()
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{reference_id}/",
        status_code=401,
    )

    with (
        get_client(Environment.LOCAL) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        verify_references(client, [_raw_enhancement(reference_id)])
