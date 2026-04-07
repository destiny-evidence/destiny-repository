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


VOCAB_URI = "https://vocab.evidence-repository.org/vocabulary/v1"


@pytest.mark.asyncio
async def test_valid_data_conforms(service: LinkedDataValidationService):
    result = await service.validate(data=VALID_DATA, vocabulary_uri=VOCAB_URI)
    assert result.conforms
    assert result.errors == []


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
