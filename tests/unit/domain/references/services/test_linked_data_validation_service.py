"""Tests for LinkedDataValidationService."""

import pytest

from app.domain.references.services.linked_data_validation_service import (
    LinkedDataValidationService,
)


@pytest.fixture
def service() -> LinkedDataValidationService:
    return LinkedDataValidationService.from_bundled_static()


EVREPO = "https://vocab.evidence-repository.org/"

VALID_DATA = {
    "@context": {"evrepo": EVREPO},
    "@type": "evrepo:LinkedDataEnhancement",
    "evrepo:hasInvestigation": {
        "@type": "evrepo:Investigation",
        "evrepo:hasFinding": {
            "@type": "evrepo:Finding",
            "evrepo:hasContext": {"@type": "evrepo:Context"},
            "evrepo:hasOutcome": {
                "@type": "evrepo:Outcome",
                "evrepo:name": "Reading comprehension",
            },
            "evrepo:evaluates": {
                "@type": "evrepo:Intervention",
                "evrepo:name": "Tutoring",
            },
            "evrepo:comparedTo": {"@type": "evrepo:ControlCondition"},
            "evrepo:hasArmData": {
                "@type": "evrepo:ObservedResult",
                "evrepo:forCondition": {"@type": "evrepo:Intervention"},
                "evrepo:n": {
                    "@value": 50,
                    "@type": "http://www.w3.org/2001/XMLSchema#integer",
                },
            },
            "evrepo:hasEffectEstimate": {
                "@type": "evrepo:EffectEstimate",
                "evrepo:pointEstimate": {
                    "@value": "0.35",
                    "@type": "http://www.w3.org/2001/XMLSchema#decimal",
                },
            },
        },
    },
}


def test_valid_data_conforms(service: LinkedDataValidationService):
    result = service.validate(data=VALID_DATA)
    assert result.conforms
    assert result.errors == []


def test_missing_required_property_fails(service: LinkedDataValidationService):
    """Finding missing required properties fails validation."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:LinkedDataEnhancement",
        "evrepo:hasInvestigation": {
            "@type": "evrepo:Investigation",
            "evrepo:hasFinding": {
                "@type": "evrepo:Finding",
            },
        },
    }
    result = service.validate(data=data)
    assert not result.conforms
    assert any("SHACL validation failed" in e for e in result.errors)


def test_invalid_concept_uri_fails(service: LinkedDataValidationService):
    """Using a concept URI that doesn't exist in the vocabulary."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:EffectEstimate",
        "evrepo:effectSizeMetric": {
            "@id": f"{EVREPO}bogusMetric",
        },
    }
    result = service.validate(data=data)
    assert not result.conforms
    assert any("bogusMetric" in e for e in result.errors)


def test_valid_concept_uri_passes(service: LinkedDataValidationService):
    """Using a valid concept URI that exists in the vocabulary."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:EffectEstimate",
        "evrepo:effectSizeMetric": {
            "@id": f"{EVREPO}hedgesG",
        },
        "evrepo:pointEstimate": {
            "@value": "0.5",
            "@type": "http://www.w3.org/2001/XMLSchema#decimal",
        },
    }
    result = service.validate(data=data)
    # SHACL may flag missing required props on EffectEstimate depending on shapes,
    # but the concept URI itself should be valid
    assert not any("bogus" in e for e in result.errors)
    assert not any("Unknown concept URI" in e for e in result.errors)


def test_empty_expansion_fails(service: LinkedDataValidationService):
    """Empty JSON-LD that expands to nothing."""
    result = service.validate(data={"@context": {}})
    assert not result.conforms
    assert any("empty graph" in e for e in result.errors)


def test_malformed_jsonld_fails(service: LinkedDataValidationService):
    """JSON-LD that cannot be expanded."""
    result = service.validate(data={"@context": 12345})
    assert not result.conforms
