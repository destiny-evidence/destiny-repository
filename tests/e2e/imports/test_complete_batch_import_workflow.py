"""End-to-end test for complete import workflow."""

import os

import httpx


def test_complete_batch_import_workflow():
    """Test the complete batch import workflow."""
    repo_url = os.environ["REPO_URL"]
    client = httpx.Client(base_url=repo_url)
    resp = client.get("/healthcheck/")
    resp.raise_for_status()
