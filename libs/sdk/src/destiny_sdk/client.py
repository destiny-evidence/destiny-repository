"""Send authenticated requests to Destiny Repository."""

import time
from collections.abc import Generator

import httpx
from msal import PublicClientApplication
from pydantic import UUID4, HttpUrl, TypeAdapter

from destiny_sdk.identifiers import IdentifierLookup
from destiny_sdk.references import Reference, ReferenceSearchResult
from destiny_sdk.robots import (
    EnhancementRequestRead,
    RobotEnhancementBatch,
    RobotEnhancementBatchRead,
    RobotEnhancementBatchResult,
    RobotResult,
)
from destiny_sdk.search import AnnotationFilter

from .auth import create_signature


class HMACSigningAuth(httpx.Auth):
    """Client that adds an HMAC signature to a request."""

    requires_request_body = True

    def __init__(self, secret_key: str, client_id: UUID4) -> None:
        """
        Initialize the client.

        :param secret_key: the key to use when signing the request
        :type secret_key: str
        """
        self.secret_key = secret_key
        self.client_id = client_id

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """
        Add a signature to the given request.

        :param request: request to be sent with signature
        :type request: httpx.Request
        :yield: Generator for Request with signature headers set
        :rtype: Generator[httpx.Request, httpx.Response]
        """
        timestamp = time.time()
        signature = create_signature(
            self.secret_key, request.content, self.client_id, timestamp
        )
        request.headers["Authorization"] = f"Signature {signature}"
        request.headers["X-Client-Id"] = f"{self.client_id}"
        request.headers["X-Request-Timestamp"] = f"{timestamp}"
        yield request


class RobotClient:
    """
    Client for interaction with the Destiny API.

    Current implementation only supports robot results.
    """

    def __init__(self, base_url: HttpUrl, secret_key: str, client_id: UUID4) -> None:
        """
        Initialize the client.

        :param base_url: The base URL for the Destiny Repository API.
        :type base_url: HttpUrl
        :param secret_key: The secret key for signing requests
        :type auth_method: str
        """
        self.session = httpx.Client(
            base_url=str(base_url).removesuffix("/").removesuffix("/v1") + "/v1",
            headers={"Content-Type": "application/json"},
            auth=HMACSigningAuth(secret_key=secret_key, client_id=client_id),
        )

    def send_robot_result(self, robot_result: RobotResult) -> EnhancementRequestRead:
        """
        Send a RobotResult to destiny repository.

        Signs the request with the client's secret key.

        :param robot_result: The RobotResult to send
        :type robot_result: RobotResult
        :return: The EnhancementRequestRead object from the response.
        :rtype: EnhancementRequestRead
        """
        response = self.session.post(
            f"/enhancement-requests/{robot_result.request_id}/results/",
            json=robot_result.model_dump(mode="json"),
        )
        response.raise_for_status()
        return EnhancementRequestRead.model_validate(response.json())

    def send_robot_enhancement_batch_result(
        self, robot_enhancement_batch_result: RobotEnhancementBatchResult
    ) -> RobotEnhancementBatchRead:
        """
        Send a RobotEnhancementBatchResult to destiny repository.

        Signs the request with the client's secret key.

        :param robot_enhancement_batch_result: The RobotEnhancementBatchResult to send
        :type robot_enhancement_batch_result: RobotEnhancementBatchResult
        :return: The RobotEnhancementBatchRead object from the response.
        :rtype: RobotEnhancementBatchRead
        """
        response = self.session.post(
            f"/robot-enhancement-batches/{robot_enhancement_batch_result.request_id}/results/",
            json=robot_enhancement_batch_result.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RobotEnhancementBatchRead.model_validate(response.json())

    def poll_robot_enhancement_batch(
        self,
        robot_id: UUID4,
        limit: int = 10,
        lease: str | None = None,
        timeout: int = 60,
    ) -> RobotEnhancementBatch | None:
        """
        Poll for a robot enhancement batch.

        Signs the request with the client's secret key.

        :param robot_id: The ID of the robot to poll for
        :type robot_id: UUID4
        :param limit: The maximum number of pending enhancements to return
        :type limit: int
        :param lease: The duration to lease the pending enhancements for,
            in ISO 8601 duration format eg PT10M. If not provided the repository will
            use a default lease duration.
        :type lease: str | None
        :return: The RobotEnhancementBatch object from the response, or None if no
            batches available
        :rtype: destiny_sdk.robots.RobotEnhancementBatch | None
        """
        params = {"robot_id": str(robot_id), "limit": limit}
        if lease:
            params["lease"] = lease
        response = self.session.post(
            "/robot-enhancement-batches/",
            params=params,
            timeout=timeout,
        )
        # HTTP 204 No Content indicates no batches available
        if response.status_code == httpx.codes.NO_CONTENT:
            return None

        response.raise_for_status()
        return RobotEnhancementBatch.model_validate(response.json())

    def renew_robot_enhancement_batch_lease(
        self, robot_enhancement_batch_id: UUID4, lease_duration: str | None = None
    ) -> None:
        """
        Renew the lease for a robot enhancement batch.

        Signs the request with the client's secret key.

        :param robot_enhancement_batch_id: The ID of the robot enhancement batch
        :type robot_enhancement_batch_id: UUID4
        :param lease_duration: The duration to lease the pending enhancements for,
            in ISO 8601 duration format eg PT10M. If not provided the repository will
            use a default lease duration.
        :type lease_duration: str | None
        """
        response = self.session.post(
            f"/robot-enhancement-batches/{robot_enhancement_batch_id}/renew-lease/",
            params={"lease": lease_duration} if lease_duration else None,
        )
        response.raise_for_status()


# Backward compatibility
Client = RobotClient


class OAuth2TokenRefreshAuth(httpx.Auth):
    """Auth middleware that handles OAuth2 token refresh on expiration."""

    def __init__(self, oauth_app: PublicClientApplication, scope: str) -> None:
        """
        Initialize the auth middleware.

        :param oauth_app: The MSAL PublicClientApplication instance.
        :type oauth_app: PublicClientApplication
        :param scope: The OAuth2 scope to request.
        :type scope: str
        """
        self._oauth_app = oauth_app
        self._scope = scope
        self._account = None

    def _get_token(self) -> str:
        """
        Get an OAuth2 token.

        :return: The OAuth2 token.
        :rtype: str
        """
        result = self._oauth_app.acquire_token_silent(
            scopes=[self._scope],
            account=self._account,
        )
        if not result:
            result = self._oauth_app.acquire_token_interactive(scopes=[self._scope])

        if not result.get("access_token"):
            msg = (
                "Failed to acquire access token: "
                f"{result.get('error', 'Unknown error')}"
            )
            raise RuntimeError(msg)

        if not self._account:
            self._account = result.get("account")
        return result["access_token"]

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """
        Add OAuth2 token to request and handle token refresh on expiration.

        :param request: The request to authenticate.
        :type request: httpx.Request
        :yield: Authenticated request with token refresh handling.
        :rtype: Generator[httpx.Request, httpx.Response]
        """
        # Add initial token
        token = self._get_token()
        request.headers["Authorization"] = f"Bearer {token}"

        response = yield request

        # Check if token expired and retry once with fresh token
        if response.status_code == httpx.codes.UNAUTHORIZED:
            try:
                json_response: dict = response.json()
                error_detail: str = json_response.get("detail", {})
            except ValueError:
                error_detail = ""

            if error_detail == "Token has expired.":
                # Refresh token and retry
                token = self._get_token()
                request.headers["Authorization"] = f"Bearer {token}"
                yield request


class OAuthClient:
    """Client for interaction with the Destiny API using OAuth2."""

    def __init__(
        self,
        base_url: HttpUrl,
        azure_tenant_id: str,
        azure_client_id: str,
        azure_application_id: str,
        azure_login_url: str = "https://login.microsoftonline.com/",
    ) -> None:
        """
        Initialize the client.

        :param base_url: The base URL for the Destiny Repository API.
        :type base_url: HttpUrl
        :param tenant_id: The OAuth2 tenant ID.
        :type tenant_id: str
        :param client_id: The OAuth2 client ID.
        :type client_id: str
        :param application_id: The application ID for the Destiny API.
        :type application_id: str
        """
        oauth_app = PublicClientApplication(
            azure_client_id,
            authority=f"{azure_login_url}{azure_tenant_id}",
            client_credential=None,
        )
        scope = f"api://{azure_application_id}/.default"
        self._client = httpx.Client(
            base_url=str(base_url).removesuffix("/").removesuffix("/v1") + "/v1",
            headers={"Content-Type": "application/json"},
            auth=OAuth2TokenRefreshAuth(oauth_app=oauth_app, scope=scope),
        )

    def search(  # noqa: PLR0913
        self,
        query: str,
        start_year: int | None = None,
        end_year: int | None = None,
        annotations: list[str | AnnotationFilter] | None = None,
        sort: str | None = None,
        page: int = 1,
    ) -> ReferenceSearchResult:
        """
        Send a search request to the Destiny Repository API.

        :param endpoint: The endpoint to send the request to.
        :type endpoint: str
        :param params: The query parameters for the search.
        :type params: dict
        :return: The response from the API.
        :rtype: httpx.Response
        """
        response = self._client.get(
            "/references/search/",
            params={
                "q": query,
                "start_year": start_year,
                "end_year": end_year,
                "annotation": [str(annotation) for annotation in annotations]
                if annotations
                else None,
                "sort": sort,
                "page": page,
            },
        )
        response.raise_for_status()
        return ReferenceSearchResult.model_validate(response.json())

    def lookup(
        self,
        identifiers: list[str | IdentifierLookup],
    ) -> list[Reference]:
        """
        Lookup references by external identifiers.

        :param identifiers: The identifiers to look up.
        :type identifiers: str | IdentifierLookup | list[str] | list[IdentifierLookup]
        :return: The list of references matching the identifiers.
        :rtype: list[Reference]
        """
        response = self._client.get(
            "/references/lookup/",
            params={"identifier": [str(identifier) for identifier in identifiers]},
        )
        response.raise_for_status()
        references_data = response.json()
        return TypeAdapter(list[Reference]).validate_python(references_data)
