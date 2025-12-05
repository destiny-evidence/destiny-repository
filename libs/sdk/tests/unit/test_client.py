"""Tests client authentication"""

import time
import uuid

import httpx
import pytest
from destiny_sdk.client import (
    OAuthClient,
    OAuthMiddleware,
    RobotClient,
    create_signature,
)
from destiny_sdk.identifiers import IdentifierLookup
from destiny_sdk.references import Reference, ReferenceSearchResult
from destiny_sdk.robots import (
    RobotEnhancementBatchRead,
    RobotEnhancementBatchResult,
    RobotError,
)
from destiny_sdk.search import AnnotationFilter
from msal import (
    ConfidentialClientApplication,
    ManagedIdentityClient,
    PublicClientApplication,
)
from pydantic import HttpUrl
from pytest_httpx import HTTPXMock


@pytest.fixture
def frozen_time(monkeypatch):
    def frozen_timestamp():
        return 12345453.32423

    monkeypatch.setattr(time, "time", frozen_timestamp)


@pytest.fixture
def base_url():
    return "https://api.destiny.example.com"


@pytest.fixture
def test_reference_id():
    return uuid.uuid4()


@pytest.fixture
def mock_reference_response(test_reference_id):
    return {
        "id": str(test_reference_id),
        "visibility": "public",
        "identifiers": [],
        "enhancements": [],
    }


class TestRobotClient:
    """Tests for RobotClient HMAC authentication."""

    def test_verify_hmac_headers_sent(
        self,
        httpx_mock: HTTPXMock,
        frozen_time,
    ) -> None:
        """Test that robot enhancement batch result request is authorized."""
        fake_secret_key = "asdfhjgji94523q0uflsjf349wjilsfjd9q23"
        fake_robot_id = uuid.uuid4()
        fake_destiny_repository_url = (
            "https://www.destiny-repository-lives-here.co.au/v1"
        )

        fake_batch_result = RobotEnhancementBatchResult(
            request_id=uuid.uuid4(),
            error=RobotError(message="Cannot process this batch"),
        )

        expected_response_body = RobotEnhancementBatchRead(
            id=uuid.uuid4(),
            robot_id=uuid.uuid4(),
            error="Cannot process this batch",
        )

        expected_signature = create_signature(
            secret_key=fake_secret_key,
            request_body=fake_batch_result.model_dump_json().encode(),
            client_id=fake_robot_id,
            timestamp=time.time(),
        )

        httpx_mock.add_response(
            url=fake_destiny_repository_url
            + "/robot-enhancement-batches/"
            + f"{fake_batch_result.request_id}/results/",
            method="POST",
            match_headers={
                "Authorization": f"Signature {expected_signature}",
                "X-Client-Id": f"{fake_robot_id}",
                "X-Request-Timestamp": f"{time.time()}",
            },
            json=expected_response_body.model_dump(mode="json"),
        )

        RobotClient(
            base_url=HttpUrl(fake_destiny_repository_url),
            secret_key=fake_secret_key,
            client_id=fake_robot_id,
        ).send_robot_enhancement_batch_result(
            robot_enhancement_batch_result=fake_batch_result,
        )

        callback_request = httpx_mock.get_requests()
        assert len(callback_request) == 1


class TestOAuthClient:
    """Tests for OAuthClient without authentication."""

    @pytest.fixture
    def oauth_client(self, base_url):
        return OAuthClient(base_url=base_url, auth=None)

    def test_search_unauthenticated(
        self,
        httpx_mock: HTTPXMock,
        oauth_client: OAuthClient,
        base_url: str,
        test_reference_id: uuid.UUID,
        mock_reference_response: dict,
    ) -> None:
        """Test that search works without authentication."""
        httpx_mock.add_response(
            url=f"{base_url}/v1/references/search/?q=test+query&page=1",
            method="GET",
            json={
                "references": [mock_reference_response],
                "page": {
                    "count": 1,
                    "number": 1,
                },
                "total": {
                    "count": 1,
                    "is_lower_bound": False,
                },
            },
        )

        result = oauth_client.search(query="test query")

        assert isinstance(result, ReferenceSearchResult)
        assert len(result.references) == 1
        assert result.references[0].id == test_reference_id
        assert result.total.count == 1

    def test_search_with_filters(
        self,
        httpx_mock: HTTPXMock,
        oauth_client: OAuthClient,
        base_url: str,
        mock_reference_response: dict,
    ) -> None:
        """Test search with year filters, annotations, and sorting."""
        httpx_mock.add_response(
            url=f"{base_url}/v1/references/search/?q=test&page=2&start_year=2020&end_year=2023&annotation=inclusion:destiny&annotation=taxonomy:biology&annotation=inclusion:otherdomain@0.5&sort=-year",
            method="GET",
            json={
                "references": [mock_reference_response],
                "total": {
                    "count": 21,
                    "is_lower_bound": False,
                },
                "page": {
                    "count": 1,
                    "number": 2,
                },
                "page_size": 10,
            },
        )

        result = oauth_client.search(
            query="test",
            start_year=2020,
            end_year=2023,
            annotations=[
                "inclusion:destiny",
                AnnotationFilter(scheme="taxonomy", label="biology"),
                AnnotationFilter(scheme="inclusion", label="otherdomain", score=0.5),
            ],
            sort="-year",
            page=2,
        )

        assert isinstance(result, ReferenceSearchResult)
        assert result.page.number == 2

    def test_lookup(
        self,
        httpx_mock: HTTPXMock,
        oauth_client: OAuthClient,
        base_url: str,
        test_reference_id: uuid.UUID,
    ) -> None:
        """Test lookup references by identifiers."""
        httpx_mock.add_response(
            url=f"{base_url}/v1/references/?identifier=doi%3A10.1234%2Ftest%2Cpm_id%3A123456%2C{test_reference_id}",
            method="GET",
            json=[
                {
                    "id": str(test_reference_id),
                    "visibility": "public",
                    "identifiers": [
                        {"identifier_type": "doi", "identifier": "10.1234/test"},
                        {"identifier_type": "pm_id", "identifier": "123456"},
                    ],
                    "enhancements": [],
                }
            ],
        )

        results = oauth_client.lookup(
            identifiers=[
                "doi:10.1234/test",
                IdentifierLookup(identifier="123456", identifier_type="pm_id"),
                IdentifierLookup(
                    identifier=str(test_reference_id),
                    identifier_type=None,
                ),
            ]
        )

        assert len(results) == 1
        assert isinstance(results[0], Reference)
        assert results[0].id == test_reference_id

    def test_handles_error_responses(
        self, httpx_mock: HTTPXMock, oauth_client: OAuthClient, base_url: str
    ) -> None:
        """Test that client properly handles error responses."""
        httpx_mock.add_response(
            url=f"{base_url}/v1/references/search/?q=test&page=1",
            method="GET",
            status_code=400,
            json={"detail": "Invalid query parameter"},
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            oauth_client.search(query="test")

        assert "400" in str(exc_info.value)
        assert "Invalid query parameter" in str(exc_info.value)


class TestOAuthMiddleware:
    """Tests for OAuthMiddleware authentication."""

    @pytest.fixture
    def mock_public_client_app(self):
        """Mock PublicClientApplication for testing."""
        mock_token = "test_access_token_123"

        class MockPublicClientApp(PublicClientApplication):
            def __init__(self, *args, **kwargs):
                # Don't call super().__init__ to avoid actual MSAL initialization
                pass

            def acquire_token_silent(self, scopes, account, *, force_refresh=False):
                if force_refresh:
                    return {"access_token": f"{mock_token}_refreshed"}
                return {"access_token": mock_token}

            def get_accounts(self):
                return []

        return MockPublicClientApp

    @pytest.fixture
    def mock_confidential_client_app(self):
        """Mock ConfidentialClientApplication for testing."""
        mock_token = "confidential_token_456"

        class MockConfidentialClientApp(ConfidentialClientApplication):
            def __init__(self, *args, **kwargs):
                # Don't call super().__init__ to avoid actual MSAL initialization
                pass

            def acquire_token_for_client(self, scopes):
                return {"access_token": mock_token}

        return MockConfidentialClientApp

    def test_public_client_auth_flow(self, monkeypatch, mock_public_client_app) -> None:
        """Test OAuth middleware auth flow with public client."""
        mock_token = "test_access_token_123"

        # Patch the class before instantiation
        monkeypatch.setattr(
            "destiny_sdk.client.PublicClientApplication",
            mock_public_client_app,
        )

        middleware = OAuthMiddleware(
            azure_login_url="test-url",
            azure_client_id="test-client",
            azure_application_id="test-app",
        )

        # Create a test request
        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute the auth flow
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        assert "Authorization" in authenticated_request.headers
        assert authenticated_request.headers["Authorization"] == f"Bearer {mock_token}"

    def test_confidential_client_auth_flow(
        self, monkeypatch, mock_confidential_client_app
    ) -> None:
        """Test OAuth middleware auth flow with confidential client."""
        mock_token = "confidential_token_456"

        # Patch the class before instantiation
        monkeypatch.setattr(
            "destiny_sdk.client.ConfidentialClientApplication",
            mock_confidential_client_app,
        )

        middleware = OAuthMiddleware(
            azure_login_url="test-url",
            azure_client_id="test-client",
            azure_application_id="test-app",
            azure_client_secret="test-secret",
        )

        # Create a test request
        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute the auth flow
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        assert "Authorization" in authenticated_request.headers
        assert authenticated_request.headers["Authorization"] == f"Bearer {mock_token}"

    def test_managed_identity_auth_flow(self, monkeypatch) -> None:
        """Test OAuth middleware auth flow with managed identity."""

        mock_token = "managed_identity_token_789"

        class MockManagedIdentityClient(ManagedIdentityClient):
            def __init__(self, *args, **kwargs):
                # Don't call super().__init__ to avoid actual MSAL initialization
                pass

            def acquire_token_for_client(self, resource):
                return {"access_token": mock_token}

        # Patch the class before instantiation
        monkeypatch.setattr(
            "destiny_sdk.client.ManagedIdentityClient",
            MockManagedIdentityClient,
        )

        middleware = OAuthMiddleware(
            use_managed_identity=True,
            azure_client_id="test-client",
            azure_application_id="test-app",
        )

        # Create a test request
        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute the auth flow
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        assert "Authorization" in authenticated_request.headers
        assert authenticated_request.headers["Authorization"] == f"Bearer {mock_token}"

    def test_token_refresh_on_expiry(self, monkeypatch, mock_public_client_app) -> None:
        """Test that middleware refreshes token when receiving 401."""
        mock_token = "test_access_token_123"
        mock_refreshed_token = f"{mock_token}_refreshed"
        call_count = {"count": 0}

        class MockPublicClientAppWithCount(mock_public_client_app):
            def acquire_token_silent(self, scopes, account, *, force_refresh=False):
                call_count["count"] += 1
                return super().acquire_token_silent(
                    scopes, account, force_refresh=force_refresh
                )

        monkeypatch.setattr(
            "destiny_sdk.client.PublicClientApplication",
            MockPublicClientAppWithCount,
        )

        middleware = OAuthMiddleware(
            azure_login_url="test-url",
            azure_client_id="test-client",
            azure_application_id="test-app",
        )

        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute the auth flow
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        # Simulate token expiry response
        expired_response = httpx.Response(
            status_code=401,
            json={"detail": "Token has expired."},
            request=authenticated_request,
        )

        # Send the expired response and get the retry request
        retry_request = flow.send(expired_response)

        # Verify token was refreshed
        assert (
            retry_request.headers["Authorization"] == f"Bearer {mock_refreshed_token}"
        )
        assert call_count["count"] == 2  # Initial + refresh
