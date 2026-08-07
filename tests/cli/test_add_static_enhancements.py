"""Tests for the static enhancement utility's input handling and robot safeguards."""

import argparse
import datetime
from pathlib import Path
from uuid import UUID, uuid7

import httpx
import pytest
from destiny_sdk.client import RobotClient
from destiny_sdk.enhancements import (
    AnnotationEnhancement,
    BooleanAnnotation,
    Enhancement,
    EnhancementFileInput,
    RawEnhancement,
    Visibility,
)
from destiny_sdk.robots import (
    ProvisionedRobot,
    Robot,
    RobotEnhancementBatch,
    RobotEntitlement,
)
from pydantic import HttpUrl
from pytest_httpx import HTTPXMock

from app.core.config import Environment
from cli.add_static_enhancements import (
    ROBOT_OWNER_MARKER,
    _fulfil_batch,
    describe_robot,
    enhancement_input,
    load_enhancements,
    required_entitlements,
    resolve_robot,
)
from cli.client import get_client

SOURCE = "galenos-lsr-export@2026-08-05"

ANNOTATION = AnnotationEnhancement(
    annotations=[
        BooleanAnnotation(scheme="domain-inclusion", label="galenos", value=True)
    ]
)
RAW = RawEnhancement(
    source_export_date=datetime.datetime(2026, 8, 5, tzinfo=datetime.UTC),
    description="A GALENOS study row.",
    data={"LSR number": "1"},
)


def _enhancement(reference_id: UUID, content: object) -> Enhancement:
    """Build an enhancement of the given content for a reference."""
    return Enhancement(
        reference_id=reference_id,
        source=SOURCE,
        visibility=Visibility.PUBLIC,
        content=content,  # type: ignore[arg-type]
    )


def _enhancement_file(tmp_path: Path, *enhancements: Enhancement) -> Path:
    """Write enhancements to a .jsonl file."""
    file = tmp_path / "enhancements.jsonl"
    file.write_text("\n".join(enhancement.to_jsonl() for enhancement in enhancements))
    return file


def _robot(owner: str, entitlements: set[RobotEntitlement] | None = None) -> Robot:
    """Build a registered robot owned by the given owner."""
    return Robot(
        id=uuid7(),
        name="galenos-static-enhancements",
        description="Writes GALENOS study data.",
        owner=owner,
        entitlements=entitlements or set(),
    )


def test_enhancement_is_applied_to_every_reference_id(tmp_path: Path) -> None:
    """One `EnhancementFileInput` is applied to each id, ignoring repeats and blanks."""
    first, second = uuid7(), uuid7()
    file = tmp_path / "references.txt"
    file.write_text(f"{first}\n{second}\n\n{second}\n")

    enhancements = load_enhancements(
        None,
        file,
        EnhancementFileInput(
            source=SOURCE, visibility=Visibility.PUBLIC, content=ANNOTATION
        ),
    )

    assert enhancements.keys() == {first, second}
    assert {enhancement.source for enhancement in enhancements.values()} == {SOURCE}


def test_two_enhancements_for_one_reference_are_rejected(tmp_path: Path) -> None:
    """A reference can only be enhanced once per request, so this input is refused."""
    reference_id = uuid7()
    file = _enhancement_file(
        tmp_path,
        _enhancement(reference_id, ANNOTATION),
        _enhancement(reference_id, RAW),
    )

    with pytest.raises(
        ValueError,
        match="Duplicate enhancements for the same reference id are not allowed",
    ):
        load_enhancements(file, None, None)


def test_only_raw_enhancements_require_an_entitlement() -> None:
    """Raw enhancements need an entitlement to write; other content does not."""
    annotation = _enhancement(uuid7(), ANNOTATION)
    raw = _enhancement(uuid7(), RAW)

    assert required_entitlements([annotation]) == set()
    assert required_entitlements([annotation, raw]) == {
        RobotEntitlement.RAW_ENHANCEMENT_WRITER
    }


def test_malformed_enhancement_json_fails_at_parse_time() -> None:
    """An unparseable ``--enhancement`` reports pydantic's complaint, not a trace."""
    with pytest.raises(argparse.ArgumentTypeError, match="visibility"):
        enhancement_input('{"source": "x", "content": {"enhancement_type": "raw"}}')


def test_robot_we_did_not_provision_is_refused(httpx_mock: HTTPXMock) -> None:
    """Another robot's secret is not ours to cycle, nor its queue ours to claim."""
    robot = _robot(owner="destiny")
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/robots/{robot.id}/",
        json=robot.model_dump(mode="json"),
    )

    with (
        get_client(Environment.LOCAL) as client,
        pytest.raises(ValueError, match="not provisioned by this utility"),
    ):
        resolve_robot(client, robot.id, None, set())


def test_robot_missing_an_entitlement_is_refused(httpx_mock: HTTPXMock) -> None:
    """A robot of ours is still refused if it cannot write the given enhancements."""
    robot = _robot(owner=ROBOT_OWNER_MARKER)
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/robots/{robot.id}/",
        json=robot.model_dump(mode="json"),
    )

    with (
        get_client(Environment.LOCAL) as client,
        pytest.raises(ValueError, match="not entitled"),
    ):
        resolve_robot(client, robot.id, None, {RobotEntitlement.RAW_ENHANCEMENT_WRITER})


def test_our_own_robot_has_its_secret_cycled(httpx_mock: HTTPXMock) -> None:
    """Reusing one of our robots takes a fresh secret rather than asking for one."""
    robot = _robot(
        owner=ROBOT_OWNER_MARKER,
        entitlements={RobotEntitlement.RAW_ENHANCEMENT_WRITER},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/robots/{robot.id}/",
        json=robot.model_dump(mode="json"),
    )
    httpx_mock.add_response(
        method="POST",
        url=f"http://127.0.0.1:8000/v1/robots/{robot.id}/secret/",
        json=ProvisionedRobot(
            **robot.model_dump(), client_secret="a-fresh-secret"
        ).model_dump(mode="json"),
    )

    with get_client(Environment.LOCAL) as client:
        provisioned = resolve_robot(
            client, robot.id, None, {RobotEntitlement.RAW_ENHANCEMENT_WRITER}
        )

    assert provisioned.id == robot.id
    assert provisioned.client_secret == "a-fresh-secret"


def test_dry_run_checks_the_robot_without_cycling_its_secret(
    httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run resolves the robot for real but must not provision anything."""
    robot = _robot(owner=ROBOT_OWNER_MARKER)
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/robots/{robot.id}/",
        json=robot.model_dump(mode="json"),
    )

    # No secret cycle is registered, so httpx_mock fails the test if one is sent.
    with get_client(Environment.LOCAL) as client:
        describe_robot(client, robot.id, None, set())

    assert "Would cycle the secret" in capsys.readouterr().out


def test_batch_holding_another_requesters_reference_is_abandoned(
    httpx_mock: HTTPXMock,
) -> None:
    """Nothing is submitted for a shared queue, so the batch expires and re-queues."""
    ours, theirs = uuid7(), uuid7()
    httpx_mock.add_response(
        method="GET",
        url="https://blob.example.com/references.jsonl",
        text=f'{{"id": "{ours}"}}\n{{"id": "{theirs}"}}\n',
    )
    batch = RobotEnhancementBatch(
        id=uuid7(),
        reference_storage_url=HttpUrl("https://blob.example.com/references.jsonl"),
        result_storage_url=HttpUrl("https://blob.example.com/results.jsonl"),
    )
    robot_client = RobotClient(
        base_url=HttpUrl("http://127.0.0.1:8000"),
        secret_key="unused",
        client_id=uuid7(),
    )

    with (
        httpx.Client() as blob_client,
        pytest.raises(ValueError, match="were not requested"),
    ):
        _fulfil_batch(
            robot_client, blob_client, batch, {ours: _enhancement(ours, ANNOTATION)}
        )
