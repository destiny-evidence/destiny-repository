"""Tests for the ESConfig model."""

import pytest
from pydantic import ValidationError

from app.core.config import AzureBlobConfig, ESConfig, MinioConfig
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
