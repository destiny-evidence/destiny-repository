"""Unit tests for the LinkedDataProjector service."""

import json
from pathlib import Path

import pytest
from destiny_sdk.enhancements import LinkedDataEnhancement

from app.domain.references.services.linked_data_projection import (
    LinkedDataProjector,
)

VOCAB_DIR = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "app"
    / "static"
    / "vocab"
    / "esea"
)

ESEA_NS = "https://vocab.esea.education/"


@pytest.fixture
def projector() -> LinkedDataProjector:
    return LinkedDataProjector(
        vocabulary_path=VOCAB_DIR / "esea-vocab.ttl",
        context_path=VOCAB_DIR / "esea-context.jsonld",
    )


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def test_data() -> dict:
    """The 7d6f1092 test reference data (content.data only)."""
    with (FIXTURES_DIR / "7d6f1092-linked-data.json").open() as f:
        return json.load(f)


@pytest.fixture
def enhancement(test_data) -> LinkedDataEnhancement:
    return LinkedDataEnhancement(
        context_uri="https://vocab.esea.education/context/v1.jsonld",
        vocabulary_uri="https://vocab.esea.education/vocabulary/v1",
        data=test_data,
    )


class TestLinkedDataProjector:
    def test_extracts_coded_concept_uris(self, projector, enhancement):
        result = projector.project(enhancement)

        expected_concepts = {
            f"{ESEA_NS}C00008",  # documentType: Journal Article
            f"{ESEA_NS}C00040",  # educationTheme
            f"{ESEA_NS}C00002",  # educationLevel: Primary Education
            f"{ESEA_NS}C00189",  # sampleFeatures
            f"{ESEA_NS}C00145",  # setting
            f"{ESEA_NS}C00123",  # outcome (appears in both findings)
            f"{ESEA_NS}C00118",  # outcome (appears in both findings)
            f"{ESEA_NS}C00122",  # outcome (second finding only)
        }
        assert result.concepts == expected_concepts

    def test_excludes_numeric_coding_annotations(self, projector, enhancement):
        """NumericCodingAnnotation (sampleSize, duration) should not appear."""
        result = projector.project(enhancement)
        concept_uris = result.concepts

        # No numeric values should be in concepts
        for uri in concept_uris:
            assert uri.startswith("http"), f"Non-URI in concepts: {uri}"

    def test_excludes_string_coding_annotations(self, projector, enhancement):
        """StringCodingAnnotation (participants='Students') should not appear
        as a concept URI."""
        result = projector.project(enhancement)

        # "Students" is a string coded value, not a concept URI
        assert "Students" not in result.concepts

    def test_resolves_labels(self, projector, enhancement):
        result = projector.project(enhancement)

        assert "Journal Article" in result.labels
        assert "Primary Education" in result.labels

    def test_resolves_evaluated_properties(self, projector, enhancement):
        result = projector.project(enhancement)

        expected_properties = {
            f"{ESEA_NS}documentType",
            f"{ESEA_NS}educationTheme",
            f"{ESEA_NS}educationLevel",
            f"{ESEA_NS}sampleFeatures",
            f"{ESEA_NS}setting",
            f"{ESEA_NS}outcome",
        }
        assert result.evaluated_properties == expected_properties

    def test_not_reported_excluded_from_concepts_but_in_properties(self, projector):
        """Concepts with notReported status should be excluded from concepts
        but their property should appear in evaluated_properties."""
        data = {
            "@type": "Investigation",
            "documentType": {
                "@type": "DocumentTypeCodingAnnotation",
                "codedValue": {"@id": "esea:C00008"},
                "status": "evrepo:notReported",
            },
        }
        enhancement = LinkedDataEnhancement(
            context_uri="https://vocab.esea.education/context/v1.jsonld",
            vocabulary_uri="https://vocab.esea.education/vocabulary/v1",
            data=data,
        )
        result = projector.project(enhancement)

        assert f"{ESEA_NS}C00008" not in result.concepts
        assert f"{ESEA_NS}documentType" in result.evaluated_properties

    def test_not_applicable_excluded_from_concepts_but_in_properties(self, projector):
        data = {
            "@type": "Investigation",
            "documentType": {
                "@type": "DocumentTypeCodingAnnotation",
                "codedValue": {"@id": "esea:C00008"},
                "status": "evrepo:notApplicable",
            },
        }
        enhancement = LinkedDataEnhancement(
            context_uri="https://vocab.esea.education/context/v1.jsonld",
            vocabulary_uri="https://vocab.esea.education/vocabulary/v1",
            data=data,
        )
        result = projector.project(enhancement)

        assert f"{ESEA_NS}C00008" not in result.concepts
        assert "Journal Article" not in result.labels
        assert f"{ESEA_NS}documentType" in result.evaluated_properties

    def test_empty_data(self, projector):
        enhancement = LinkedDataEnhancement(
            context_uri="https://vocab.esea.education/context/v1.jsonld",
            vocabulary_uri="https://vocab.esea.education/vocabulary/v1",
            data={"@type": "Investigation"},
        )
        result = projector.project(enhancement)

        assert result.concepts == set()
        assert result.labels == set()
        assert result.evaluated_properties == set()

    def test_scheme_to_property_mapping(self, projector):
        mapping = projector._scheme_to_property  # noqa: SLF001
        assert mapping[f"{ESEA_NS}DocumentTypeScheme"] == (f"{ESEA_NS}documentType")
        assert mapping[f"{ESEA_NS}EducationLevelScheme"] == (f"{ESEA_NS}educationLevel")
        assert mapping[f"{ESEA_NS}EducationThemeScheme"] == (f"{ESEA_NS}educationTheme")
        assert mapping[f"{ESEA_NS}OutcomeScheme"] == f"{ESEA_NS}outcome"
