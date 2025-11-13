"""Tests for the experimental Reference class."""

import json
from pathlib import Path

from destiny_sdk.labs.references import LabsReference
from destiny_sdk.references import Reference


def _read_references():
    test_data_path = Path(__file__).parent.parent / "test_data/destiny_references.jsonl"
    with test_data_path.open() as test_references_file:
        for line in test_references_file:
            yield LabsReference(reference=Reference.from_es(json.loads(line)))


def test_annotations():
    """Test that the parse_data method returns the expected output."""

    expected = [
        (
            {"scheme": "inclusion:destiny"},
            [True, None, True, False, False, True, True, True, False, True],
        ),
        (
            {"scheme": "inclusion:destiny", "label": "Included in DESTINY domain"},
            [True, None, True, False, False, True, True, True, False, True],
        ),
        (
            {
                "scheme": "inclusion:destiny",
                "label": "Included in DESTINY domain",
                "expected_value": False,
            },
            [False, None, False, True, True, False, False, False, True, False],
        ),
        (
            {
                "scheme": "classifier:taxonomy:Context",
                "label": "Coastal socioecological systems",
            },
            [None, None, None, None, None, False, False, False, False, False],
        ),
        (
            {"scheme": "classifier:taxonomy:Context"},
            [None, None, None, None, None, True, True, True, True, True],
        ),
        (
            {"scheme": "classifier:taxonomy:Context", "expected_value": False},
            [None, None, None, None, None, True, True, True, True, True],
        ),
    ]

    for params, expected_values in expected:
        for ref, expected_value in zip(
            _read_references(), expected_values, strict=False
        ):
            assert expected_value == ref.has_bool_annotation(**params)


def test_titles():
    """Test that the parse_data method returns the expected output."""
    expected = [
        "Makro Ekonomik Zihin Teori, Politika, Dinamikler",
        "Analysis of parental beliefs and practices leading to excessive screen "
        "time in early childhood",
        "Exploring the link between A Body Shape Index and abdominal aortic "
        "calcification in chronic kidney disease: a cross-sectional analysis from "
        "2013–2014 National Health and Nutrition Examination Survey",  # noqa: RUF001
        "Microbiological Evaluation of Biodegradation Processes of Solid Waste in "
        "Reclaimed Landfills",
        "Wave-Structure Interactions of a Floating FPSO-Shaped Body",
        "Function and public awareness of sustainable development and population "
        "health projects in Montreal, Canada: a logic model and survey of the "
        "Quartiers 21 Program",
        "NGOs’ responses to the challenges faced by orphans and "  # noqa: RUF001
        "vulnerable children (OVC) in Chegutu, Zimbabwe",
        "Climate change-related health hazards in daycare centers in Munich, Germany: "
        "risk perception and adaptation measures",
        None,
        "Association of Placenta Praevia with Previous Cesarean Section in "
        "Rajshahi Medical College Hospital",
    ]
    for ref, expected_value in zip(_read_references(), expected, strict=False):
        assert expected_value == ref.title


def test_biblio():
    """Test that the parse_data method returns the expected output."""
    expected = {
        "doi": [
            "10.58830/ozgur.pub782",
            None,
            "10.1080/0886022x.2025.2517403",
            "10.54740/ros.2025.028",
            "10.31814/stce.huce2025-19(2)-11",
            "10.1016/s0140-6736(14)61878-x",
            "10.1111/issj.12473",
            "10.1007/s10113-023-02136-w",
            "10.3390/diseases11040157",
            "10.36347/sasjs.2023.v09i10.007",
        ],
        "publication_year": [
            2025,
            None,
            2025,
            2025,
            2025,
            None,
            2023,
            2023,
            2023,
            None,
        ],
        "openalex_id": [
            "W4411634280",
            "W4411634320",
            "W4411634759",
            "W4411698874",
            "W4411698892",
            "W1965074043",
            "W4388230581",
            "W4388231242",
            "W4388231278",
            "W4388232129",
        ],
        "pubmed_id": [
            None,
            40562693,
            40562394,
            None,
            None,
            None,
            None,
            None,
            37987268,
            None,
        ],
    }
    for prop, expected_values in expected.items():
        for ref, expected_value in zip(
            _read_references(), expected_values, strict=False
        ):
            assert expected_value == getattr(ref, prop)
