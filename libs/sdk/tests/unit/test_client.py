"""Tests client authentication"""

import time
from uuid import UUID, uuid7

import httpx
import pytest
from destiny_sdk.client import (
    AzureOAuthMiddleware,
    KeycloakOAuthMiddleware,
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
from pydantic import HttpUrl, SecretStr
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
    return uuid7()


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
        fake_robot_id = uuid7()
        fake_destiny_repository_url = (
            "https://www.destiny-repository-lives-here.co.au/v1"
        )

        fake_batch_result = RobotEnhancementBatchResult(
            request_id=uuid7(),
            error=RobotError(message="Cannot process this batch"),
        )

        expected_response_body = RobotEnhancementBatchRead(
            id=uuid7(),
            robot_id=uuid7(),
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
    """Tests for OAuthClient request handling."""

    @pytest.fixture
    def oauth_client(self, base_url):
        # Auth is required; use a no-op stand-in so tests focus on request shape,
        # not authentication. AzureOAuthMiddleware/KeycloakOAuthMiddleware are
        # exercised separately below.
        return OAuthClient(base_url=base_url, auth=httpx.BasicAuth("user", "pass"))

    def test_search(
        self,
        httpx_mock: HTTPXMock,
        oauth_client: OAuthClient,
        base_url: str,
        test_reference_id: UUID,
        mock_reference_response: dict,
    ) -> None:
        """Test that search builds the expected request and parses results."""
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
        test_reference_id: UUID,
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


class TestOAuthClientEnvShortcut:
    """Tests for the OAuthClient ``env`` constructor shortcut."""

    @pytest.mark.parametrize(
        ("env", "expected_base_url"),
        [
            ("development", "https://api.dev.evidence-repository.org"),
            ("staging", "https://api.staging.evidence-repository.org"),
            ("production", "https://api.evidence-repository.org"),
        ],
    )
    def test_env_derives_base_url_and_auth(
        self, env: str, expected_base_url: str
    ) -> None:
        """env fills in base_url from DEFAULT_API_URLS and builds OAuthMiddleware."""
        client = OAuthClient(env=env)  # type: ignore[arg-type]
        assert str(client._client.base_url) == f"{expected_base_url}/v1/"  # noqa: SLF001
        assert isinstance(client._client.auth, OAuthMiddleware)  # noqa: SLF001

    def test_explicit_base_url_overrides_env_default(self) -> None:
        """An explicit base_url is preserved when env is also provided."""
        client = OAuthClient(env="production", base_url="https://override.example.com")
        assert (
            str(client._client.base_url)  # noqa: SLF001
            == "https://override.example.com/v1/"
        )

    def test_explicit_auth_overrides_env_default(self, base_url: str) -> None:
        """An explicit auth is preserved when env is also provided."""
        custom_auth = httpx.BasicAuth("user", "pass")
        client = OAuthClient(env="production", base_url=base_url, auth=custom_auth)
        assert client._client.auth is custom_auth  # noqa: SLF001

    def test_rejects_missing_auth_when_env_omitted(self) -> None:
        """Without env, auth must be provided explicitly."""
        with pytest.raises(ValueError, match=r"^auth required"):
            OAuthClient(base_url="https://example.com")

    def test_rejects_missing_base_url_when_env_omitted(self) -> None:
        """Without env, base_url must be provided explicitly even if auth is."""
        with pytest.raises(ValueError, match=r"^base_url required"):
            OAuthClient(auth=httpx.BasicAuth("user", "pass"))

    def test_rejects_missing_auth_and_base_url(self) -> None:
        """When both are missing the error names both."""
        with pytest.raises(ValueError, match=r"^auth and base_url required"):
            OAuthClient()


class TestAzureOAuthMiddleware:
    """Tests for AzureOAuthMiddleware authentication."""

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

        with pytest.warns(DeprecationWarning, match="public client"):
            middleware = AzureOAuthMiddleware(
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

        with pytest.warns(DeprecationWarning, match="confidential-client"):
            middleware = AzureOAuthMiddleware(
                azure_login_url="test-url",
                azure_client_id="test-client",
                azure_application_id="test-app",
                azure_client_secret=SecretStr("test-secret"),
            )

        # Create a test request
        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute the auth flow
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        assert "Authorization" in authenticated_request.headers
        assert authenticated_request.headers["Authorization"] == f"Bearer {mock_token}"

    def test_managed_identity_auth_flow(self, monkeypatch, recwarn) -> None:
        """Test OAuth middleware auth flow with managed identity.

        Also asserts that managed identity is NOT covered by the Azure
        deprecation warning — only the public/confidential flows are.
        """

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

        middleware = AzureOAuthMiddleware(
            use_managed_identity=True,
            azure_client_id="test-client",
            azure_application_id="test-app",
        )

        deprecations = [
            w for w in recwarn.list if issubclass(w.category, DeprecationWarning)
        ]
        assert not deprecations

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

        with pytest.warns(DeprecationWarning, match="public client"):
            middleware = AzureOAuthMiddleware(
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


class TestKeycloakOAuthMiddleware:
    """Tests for KeycloakOAuthMiddleware authentication."""

    def test_client_credentials_auth_flow(self, httpx_mock: HTTPXMock) -> None:
        """Test Keycloak middleware auth flow with client credentials."""
        mock_token = "keycloak_cc_token_789"

        # Mock the Keycloak token endpoint
        httpx_mock.add_response(
            url="http://localhost:8080/realms/destiny/protocol/openid-connect/token",
            method="POST",
            json={
                "access_token": mock_token,
                "expires_in": 300,
                "token_type": "Bearer",
                "scope": "openid import.writer.all",
            },
        )

        middleware = KeycloakOAuthMiddleware(
            keycloak_url="http://localhost:8080",
            realm="destiny",
            client_id="test-service-client",
            client_secret=SecretStr("test-secret"),
            scopes=["import.writer.all"],
        )

        request = httpx.Request("GET", "https://api.example.com/test")

        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        assert "Authorization" in authenticated_request.headers
        assert authenticated_request.headers["Authorization"] == f"Bearer {mock_token}"

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    def test_client_credentials_reacquires_on_expiry(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """Test that client credentials middleware re-acquires token on 401."""
        initial_token = "keycloak_cc_token_initial"
        refreshed_token = "keycloak_cc_token_refreshed"
        call_count = {"count": 0}

        def token_response(_request, **_kwargs):
            call_count["count"] += 1
            token = refreshed_token if call_count["count"] > 1 else initial_token
            return httpx.Response(
                200,
                json={
                    "access_token": token,
                    "expires_in": 300,
                    "token_type": "Bearer",
                    "scope": "openid",
                },
            )

        httpx_mock.add_callback(
            token_response,
            url="http://localhost:8080/realms/destiny/protocol/openid-connect/token",
            method="POST",
        )

        middleware = KeycloakOAuthMiddleware(
            keycloak_url="http://localhost:8080",
            realm="destiny",
            client_id="test-service-client",
            client_secret=SecretStr("test-secret"),
        )

        request = httpx.Request("GET", "https://api.example.com/test")

        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)

        assert (
            authenticated_request.headers["Authorization"] == f"Bearer {initial_token}"
        )

        # Simulate token expiry
        expired_response = httpx.Response(
            status_code=401,
            json={"detail": "Token has expired."},
            request=authenticated_request,
        )

        retry_request = flow.send(expired_response)

        assert retry_request.headers["Authorization"] == f"Bearer {refreshed_token}"
        assert call_count["count"] == 2


class TestOAuthMiddleware:
    """Tests for the OAuthMiddleware router."""

    def test_routes_to_keycloak_on_auth_url(self, httpx_mock: HTTPXMock) -> None:
        """Keycloak kwargs route through to KeycloakOAuthMiddleware."""
        mock_token = "router_keycloak_token"
        httpx_mock.add_response(
            url="http://localhost:8080/realms/destiny/protocol/openid-connect/token",
            method="POST",
            json={
                "access_token": mock_token,
                "expires_in": 300,
                "token_type": "Bearer",
                "scope": "openid",
            },
        )

        middleware = OAuthMiddleware(
            auth_url="http://localhost:8080",
            realm="destiny",
            client_id="test-service-client",
            client_secret=SecretStr("test-secret"),
        )

        assert isinstance(middleware._inner, KeycloakOAuthMiddleware)  # noqa: SLF001

        request = httpx.Request("GET", "https://api.example.com/test")
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)
        assert authenticated_request.headers["Authorization"] == f"Bearer {mock_token}"

    def test_routes_to_azure_with_deprecation_warning(self, monkeypatch) -> None:
        """Azure public-client kwargs route through with a deprecation warning."""

        class MockPublicClientApp(PublicClientApplication):
            def __init__(self, *args, **kwargs):
                pass

            def acquire_token_silent(self, scopes, account, *, force_refresh=False):
                return {"access_token": "azure_router_token"}

            def get_accounts(self):
                return []

        monkeypatch.setattr(
            "destiny_sdk.client.PublicClientApplication", MockPublicClientApp
        )

        with pytest.warns(DeprecationWarning, match="public client"):
            middleware = OAuthMiddleware(
                azure_login_url="test-url",
                azure_client_id="test-client",
                azure_application_id="test-app",
            )

        assert isinstance(middleware._inner, AzureOAuthMiddleware)  # noqa: SLF001

        request = httpx.Request("GET", "https://api.example.com/test")
        flow = middleware.auth_flow(request)
        authenticated_request = next(flow)
        assert (
            authenticated_request.headers["Authorization"]
            == "Bearer azure_router_token"
        )

    def test_routes_to_managed_identity_without_warning(
        self, monkeypatch, recwarn
    ) -> None:
        """Managed identity is not deprecated; routing to it must not warn."""

        class MockManagedIdentityClient(ManagedIdentityClient):
            def __init__(self, *args, **kwargs):
                pass

            def acquire_token_for_client(self, resource):
                return {"access_token": "mi_token"}

        monkeypatch.setattr(
            "destiny_sdk.client.ManagedIdentityClient", MockManagedIdentityClient
        )

        middleware = OAuthMiddleware(
            use_managed_identity=True,
            azure_client_id="test-client",
            azure_application_id="test-app",
        )

        assert isinstance(middleware._inner, AzureOAuthMiddleware)  # noqa: SLF001
        deprecations = [
            w for w in recwarn.list if issubclass(w.category, DeprecationWarning)
        ]
        assert not deprecations

    def test_env_derives_client_id(self) -> None:
        """env derives client_id as destiny-auth-client-{env}."""
        middleware = OAuthMiddleware(env="staging")
        inner = middleware._inner  # noqa: SLF001
        assert isinstance(inner, KeycloakOAuthMiddleware)
        assert inner._auth_flow.client_id == "destiny-auth-client-staging"  # noqa: SLF001

    def test_explicit_client_id_overrides_env_derivation(self) -> None:
        """An explicit client_id is preserved when env is also provided."""
        middleware = OAuthMiddleware(env="production", client_id="my-explicit-client")
        inner = middleware._inner  # noqa: SLF001
        assert isinstance(inner, KeycloakOAuthMiddleware)
        assert inner._auth_flow.client_id == "my-explicit-client"  # noqa: SLF001

    def test_rejects_keycloak_without_env_or_client_id(self) -> None:
        """Keycloak path requires either env or client_id."""
        with pytest.raises(ValueError, match="client_id is required"):
            OAuthMiddleware()

    def test_azure_takes_precedence_over_keycloak_kwargs(self, monkeypatch) -> None:
        """When Azure kwargs are present, Keycloak kwargs are ignored."""

        class MockPublicClientApp(PublicClientApplication):
            def __init__(self, *args, **kwargs):
                pass

            def acquire_token_silent(self, scopes, account, *, force_refresh=False):
                return {"access_token": "azure_precedence_token"}

            def get_accounts(self):
                return []

        monkeypatch.setattr(
            "destiny_sdk.client.PublicClientApplication", MockPublicClientApp
        )

        with pytest.warns(DeprecationWarning, match="public client"):
            middleware = OAuthMiddleware(
                env="production",
                azure_login_url="test-url",
                azure_client_id="test-client",
                azure_application_id="test-app",
            )

        assert isinstance(middleware._inner, AzureOAuthMiddleware)  # noqa: SLF001
