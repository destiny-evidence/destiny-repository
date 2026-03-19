"""Tests for LinkedDataValidationService."""

from pathlib import Path

import pytest
from rdflib import Graph

from app.domain.references.services.linked_data_validation_service import (
    LinkedDataValidationService,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def service() -> LinkedDataValidationService:
    ontology = Graph()
    ontology.parse(str(_FIXTURES_DIR / "evrepo-core.ttl"), format="turtle")
    return LinkedDataValidationService(ontology=ontology)


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


def test_uri_with_comma_fails(service: LinkedDataValidationService):
    """URIs containing unencoded commas are rejected."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:EffectEstimate",
        "evrepo:effectSizeMetric": {
            "@id": f"{EVREPO}hedgesG,cohensD",
        },
    }
    result = service.validate(data=data)
    assert not result.conforms
    assert any("unencoded comma" in e for e in result.errors)


def test_empty_expansion_fails(service: LinkedDataValidationService):
    """Empty JSON-LD that expands to nothing."""
    result = service.validate(data={"@context": {}})
    assert not result.conforms
    assert any("empty graph" in e for e in result.errors)


def test_malformed_jsonld_fails(service: LinkedDataValidationService):
    """JSON-LD that cannot be expanded."""
    result = service.validate(data={"@context": 12345})
    assert not result.conforms
