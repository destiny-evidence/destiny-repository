"""Tests for the ESConfig model."""

import pytest
from pydantic import ValidationError

from app.core.config import (
    AzureBlobConfig,
    DedupAssessmentRecordingConfig,
    DedupCandidateScoringConfig,
    ESConfig,
    MinioConfig,
)
from app.domain.references.models.models import RetrievalPolicyName
from app.persistence.blob.models import BlobContainer


def test_es_config_api_key_auth():
    """Test ESConfig with API key authentication."""
    config = ESConfig(cloud_id="test-cloud-id", api_key="test-api-key")
    assert config.uses_api_key is True
    assert config.cloud_id == "test-cloud-id"
    assert config.api_key == "test-api-key"


def test_es_config_insecure_url():
    """Test ESConfig with insecure URL."""
    config = ESConfig(es_insecure_url="http://localhost:9200/")
    assert str(config.es_insecure_url) == "http://localhost:9200/"
    assert config.uses_api_key is False


def test_es_config_traditional_auth():
    """Test ESConfig with traditional authentication."""
    config = ESConfig(es_url="https://localhost:9200/", es_user="user", es_pass="pass")
    assert config.es_user == "user"
    assert config.es_pass == "pass"
    assert config.es_hosts == ["https://localhost:9200/"]


def test_es_config_invalid_auth():
    """Test ESConfig with invalid authentication setup."""
    with pytest.raises(ValidationError):
        ESConfig()


def test_es_config_multiple_auth_methods_invalid():
    """Test ESConfig with multiple conflicting authentication methods."""
    with pytest.raises(ValidationError):
        ESConfig(
            cloud_id="test-cloud-id",
            api_key="test-api-key",
            es_insecure_url="http://localhost:9200/",
            es_user="user",
            es_pass="pass",
        )


def test_blob_backend_config_requires_all_containers():
    """Backend configs must include a container for every BlobContainer value."""
    with pytest.raises(ValidationError, match="operations"):
        AzureBlobConfig(
            storage_account_name="acct",
            containers={BlobContainer.FULL_TEXTS: "full-texts"},
        )
    with pytest.raises(ValidationError, match="full_texts"):
        MinioConfig(
            host="h",
            access_key="a",
            secret_key="s",
            containers={BlobContainer.OPERATIONS: "ops"},
        )


def test_candidate_selection_config_defaults_to_production_policy_and_k():
    """Candidate selection uses the deployed policy unless explicitly overridden."""
    config = DedupCandidateScoringConfig()

    assert config.default_retrieval_policy is RetrievalPolicyName.CANDIDATE_SELECTION_V1
    assert config.candidate_k == 10


def test_dedup_assessment_recording_defaults_to_full_evidence_sample():
    """Default recording keeps every sampled evidence payload."""
    config = DedupAssessmentRecordingConfig()

    assert config.evidence_sample_rate_bits == 0


@pytest.mark.parametrize("sample_rate_bits", [None, 0, 1, 8, 64])
def test_dedup_assessment_recording_accepts_valid_sample_rate_bits(
    sample_rate_bits: int | None,
):
    """Evidence sampling is configured as a base-2 sample-rate exponent."""
    config = DedupAssessmentRecordingConfig(evidence_sample_rate_bits=sample_rate_bits)

    assert config.evidence_sample_rate_bits == sample_rate_bits


@pytest.mark.parametrize("sample_rate_bits", [-1, 65])
def test_dedup_assessment_recording_rejects_invalid_sample_rate_bits(
    sample_rate_bits: int,
):
    """The sample-rate exponent must fit the 64-bit sampler digest."""
    with pytest.raises(ValidationError):
        DedupAssessmentRecordingConfig(evidence_sample_rate_bits=sample_rate_bits)
