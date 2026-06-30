"""Tests for LinkedDataValidationService."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from rdflib import Graph

from app.core.exceptions import VocabularyFetchError
from app.domain.references.services.linked_data_validation_service import (
    LinkedDataValidationService,
)
from app.external.vocabulary.client import VocabularyArtifactClient

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def ontology() -> Graph:
    g = Graph()
    g.parse(str(_FIXTURES_DIR / "evrepo-core.ttl"), format="turtle")
    # The published HPV vocab types its applied concepts as skos:Concept; mirror
    # a few here so sh:class on hasAppliedConcept resolves.
    g.parse(
        data="""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        <https://vocab.aliveevidence.org/hpv/Country/NG> a skos:Concept .
        <https://vocab.aliveevidence.org/hpv/StudyDesign/HPVV0148> a skos:Concept .
        <https://vocab.aliveevidence.org/hpv/EquityDimension/HPVV0011> a skos:Concept .
        """,
        format="turtle",
    )
    return g


@pytest.fixture
def vocab_client(ontology: Graph) -> VocabularyArtifactClient:
    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_vocabulary = AsyncMock(return_value=ontology)
    client.get_context = AsyncMock()
    return client


@pytest.fixture
def service(vocab_client: VocabularyArtifactClient) -> LinkedDataValidationService:
    return LinkedDataValidationService(vocab_client=vocab_client)


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


VALID_DATA_WITH_ONTOLOGY_CONCEPT = {
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
                "evrepo:effectSizeMetric": {
                    "@id": "https://vocab.evidence-repository.org/hedgesG",
                },
            },
        },
    },
}


VALID_DATA_WITHOUT_ARM_DATA = {
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


HPV_DATA = {
    "@context": {"evrepo": EVREPO},
    "@type": "evrepo:LinkedDataEnhancement",
    "evrepo:hasInvestigation": {
        "@type": "evrepo:Investigation",
        "evrepo:hasAppliedConcept": [
            {"@id": "https://vocab.aliveevidence.org/hpv/Country/NG"},
            {"@id": "https://vocab.aliveevidence.org/hpv/StudyDesign/HPVV0148"},
            {"@id": "https://vocab.aliveevidence.org/hpv/EquityDimension/HPVV0011"},
        ],
    },
}


VOCAB_URI = "https://vocab.evidence-repository.org/vocabulary/v1"


@pytest.mark.asyncio
async def test_valid_data_conforms(service: LinkedDataValidationService):
    result = await service.validate(data=VALID_DATA, vocabulary_uri=VOCAB_URI)
    assert result.conforms
    assert result.errors == []


@pytest.mark.asyncio
async def test_ontology_concept_types_resolved_via_graph_merge(
    service: LinkedDataValidationService,
):
    """sh:class constraints on ontology-typed concepts pass.

    effectSizeMetric references evrepo:hedgesG, whose rdf:type
    EffectSizeMetricConcept lives in the ontology, not in the LDE data.
    Without merging the ontology into the data graph before SHACL
    validation, pyshacl cannot resolve the type and the constraint fails.
    """
    result = await service.validate(
        data=VALID_DATA_WITH_ONTOLOGY_CONCEPT, vocabulary_uri=VOCAB_URI
    )
    assert result.conforms, f"Expected conforms=True, got errors: {result.errors}"


@pytest.mark.asyncio
async def test_hpv_investigation_without_finding_conforms(
    service: LinkedDataValidationService,
):
    """HPV-style enhancement: an Investigation carrying applied concepts and no
    Finding conforms — hasFinding is optional."""
    result = await service.validate(data=HPV_DATA, vocabulary_uri=VOCAB_URI)
    assert result.conforms, f"Expected conforms=True, got errors: {result.errors}"
    assert result.errors == []


@pytest.mark.asyncio
async def test_investigation_with_multiple_findings_conforms(
    service: LinkedDataValidationService,
):
    """An Investigation may hold more than one Finding."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:LinkedDataEnhancement",
        "evrepo:hasInvestigation": {
            "@type": "evrepo:Investigation",
            "evrepo:hasFinding": [
                {
                    "@type": "evrepo:Finding",
                    "evrepo:hasOutcome": {
                        "@type": "evrepo:Outcome",
                        "evrepo:name": "Reading comprehension",
                    },
                },
                {
                    "@type": "evrepo:Finding",
                    "evrepo:hasContext": {"@type": "evrepo:Context"},
                },
            ],
        },
    }
    result = await service.validate(data=data, vocabulary_uri=VOCAB_URI)
    assert result.conforms, f"Expected conforms=True, got errors: {result.errors}"


@pytest.mark.asyncio
async def test_investigation_with_findings_and_applied_concepts_conforms(
    service: LinkedDataValidationService,
):
    """Findings and applied concepts may coexist on the same Investigation."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:LinkedDataEnhancement",
        "evrepo:hasInvestigation": {
            "@type": "evrepo:Investigation",
            "evrepo:hasFinding": {
                "@type": "evrepo:Finding",
                "evrepo:hasOutcome": {
                    "@type": "evrepo:Outcome",
                    "evrepo:name": "Reading comprehension",
                },
            },
            "evrepo:hasAppliedConcept": [
                {"@id": "https://vocab.aliveevidence.org/hpv/Country/NG"},
            ],
        },
    }
    result = await service.validate(data=data, vocabulary_uri=VOCAB_URI)
    assert result.conforms, f"Expected conforms=True, got errors: {result.errors}"


@pytest.mark.asyncio
async def test_applied_concept_literal_fails(service: LinkedDataValidationService):
    """hasAppliedConcept values must be IRIs, not literals."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:LinkedDataEnhancement",
        "evrepo:hasInvestigation": {
            "@type": "evrepo:Investigation",
            "evrepo:hasAppliedConcept": "not-an-iri",
        },
    }
    result = await service.validate(data=data, vocabulary_uri=VOCAB_URI)
    assert not result.conforms
    assert any("SHACL validation failed" in e for e in result.errors)


@pytest.mark.asyncio
async def test_applied_concept_not_a_concept_fails(
    service: LinkedDataValidationService,
):
    """An applied-concept IRI the vocab doesn't type as skos:Concept fails."""
    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:LinkedDataEnhancement",
        "evrepo:hasInvestigation": {
            "@type": "evrepo:Investigation",
            "evrepo:hasAppliedConcept": [
                {"@id": "https://vocab.aliveevidence.org/hpv/Country/ZZ"},
            ],
        },
    }
    result = await service.validate(data=data, vocabulary_uri=VOCAB_URI)
    assert not result.conforms
    assert any("SHACL validation failed" in e for e in result.errors)


@pytest.mark.asyncio
async def test_applied_concept_subclass_of_concept_conforms():
    """An applied concept typed as a subclass of skos:Concept conforms —
    sh:class is subclass-aware under inference="none"."""
    ontology = Graph()
    ontology.parse(
        data="""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <https://vocab.aliveevidence.org/hpv/Country> a owl:Class ;
            rdfs:subClassOf skos:Concept .
        <https://vocab.aliveevidence.org/hpv/Country/NG> a
            <https://vocab.aliveevidence.org/hpv/Country> .
        """,
        format="turtle",
    )
    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_vocabulary = AsyncMock(return_value=ontology)
    client.get_context = AsyncMock()
    service = LinkedDataValidationService(vocab_client=client)

    data = {
        "@context": {"evrepo": EVREPO},
        "@type": "evrepo:LinkedDataEnhancement",
        "evrepo:hasInvestigation": {
            "@type": "evrepo:Investigation",
            "evrepo:hasAppliedConcept": [
                {"@id": "https://vocab.aliveevidence.org/hpv/Country/NG"},
            ],
        },
    }
    result = await service.validate(data=data, vocabulary_uri=VOCAB_URI)
    assert result.conforms, f"Expected conforms=True, got errors: {result.errors}"


@pytest.mark.asyncio
async def test_finding_without_arm_data_conforms(service: LinkedDataValidationService):
    """Finding without hasArmData should conform — arm data is optional."""
    result = await service.validate(
        data=VALID_DATA_WITHOUT_ARM_DATA, vocabulary_uri=VOCAB_URI
    )
    assert result.conforms, f"Expected conforms=True, got errors: {result.errors}"


@pytest.mark.asyncio
async def test_missing_required_property_fails(service: LinkedDataValidationService):
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
    result = await service.validate(data=data, vocabulary_uri=VOCAB_URI)
    assert not result.conforms
    assert any("SHACL validation failed" in e for e in result.errors)


@pytest.mark.asyncio
async def test_empty_expansion_fails(service: LinkedDataValidationService):
    """Empty JSON-LD that expands to nothing."""
    result = await service.validate(data={"@context": {}}, vocabulary_uri=VOCAB_URI)
    assert not result.conforms
    assert any("empty graph" in e for e in result.errors)


@pytest.mark.asyncio
async def test_malformed_jsonld_fails(service: LinkedDataValidationService):
    """JSON-LD that cannot be expanded."""
    result = await service.validate(data={"@context": 12345}, vocabulary_uri=VOCAB_URI)
    assert not result.conforms


@pytest.mark.asyncio
async def test_vocabulary_fetch_error_propagates(
    vocab_client: MagicMock,
):
    """VocabularyFetchError propagates instead of returning conforms=False."""
    vocab_client.get_vocabulary = AsyncMock(
        side_effect=VocabularyFetchError("http://example.com", "connection refused"),
    )
    service = LinkedDataValidationService(vocab_client=vocab_client)
    with pytest.raises(VocabularyFetchError):
        await service.validate(data=VALID_DATA, vocabulary_uri=VOCAB_URI)
