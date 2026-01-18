"""Send authenticated requests to Destiny Repository."""

import sys
import time
from collections.abc import Generator

import httpx
from msal import (
    ConfidentialClientApplication,
    ManagedIdentityClient,
    PublicClientApplication,
    UserAssignedManagedIdentity,
)
from pydantic import UUID4, HttpUrl, TypeAdapter

from destiny_sdk.auth import create_signature
from destiny_sdk.core import sdk_version
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

python_version = ".".join(map(str, sys.version_info[:3]))
user_agent = f"python@{python_version}/destiny-sdk@{sdk_version}"


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
            headers={
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
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


class OAuthMiddleware(httpx.Auth):
    """
    Auth middleware that handles OAuth2 token retrieval and refresh.

    This is generally used in conjunction with
    :class:`OAuthClient <libs.sdk.src.destiny_sdk.client.OAuthClient>`.

    Supports three authentication flows:

    **Public Client Application (human login)**

    Initial login will be interactive through a browser window. Subsequent token
    retrievals will use cached tokens and refreshes where possible, and only prompt
    for login again if necessary.

    .. code-block:: python

        auth = OAuthMiddleware(
            azure_client_id="client-id",
            azure_application_id="application-id",
            azure_login_url="login-url",
        )

    **Confidential Client Application (client credentials)**

    Suitable for service-to-service authentication where no user interaction is
    possible or desired. Reach out if you need help setting up a confidential client
    application. The secret must be stored securely.

    .. code-block:: python

        auth = OAuthMiddleware(
            azure_client_id="client-id",
            azure_application_id="application-id",
            azure_login_url="login-url",
            azure_client_secret="your-azure-client-secret",
        )

    **Azure Managed Identity**

    Suitable for Azure environments that have had API permissions provisioned for
    their managed identity. Note that the ``azure_client_id`` here is the client ID of
    the managed identity, not the repository.

    .. code-block:: python

        auth = OAuthMiddleware(
            azure_client_id="your-managed-identity-client-id",
            azure_application_id="application-id",
            use_managed_identity=True,
        )

    """

    def __init__(
        self,
        azure_client_id: str,
        azure_application_id: str,
        azure_login_url: HttpUrl | str | None = None,
        azure_client_secret: str | None = None,
        *,
        use_managed_identity: bool = False,
    ) -> None:
        """
        Initialize the auth middleware.

        :param azure_client_id: The OAuth2 client ID.
        :type azure_client_id: str
        :param azure_application_id: The application ID for the Destiny API.
        :type application_id: str
        :param azure_login_url: The Azure login URL.
        :type azure_login_url: str
        :param azure_client_secret: The Azure client secret.
        :type azure_client_secret: str | None
        :param use_managed_identity: Whether to use managed identity for authentication
        :type use_managed_identity: bool
        """
        if use_managed_identity:
            if (
                any(
                    [
                        azure_login_url,
                        azure_client_secret,
                    ]
                )
                or not azure_client_id
            ):
                msg = (
                    "azure_login_url and azure_client_secret must not be provided "
                    "when using managed identity authentication"
                )
                raise ValueError(msg)
            self._oauth_app = ManagedIdentityClient(
                UserAssignedManagedIdentity(client_id=azure_client_id),
                http_client=httpx.Client(),
            )
            self._get_token = self._get_token_from_managed_identity
        elif azure_client_secret:
            if not azure_login_url:
                msg = (
                    "azure_login_url must be provided "
                    "when not using managed identity authentication"
                )
                raise ValueError(msg)
            self._oauth_app = ConfidentialClientApplication(
                client_id=azure_client_id,
                authority=str(azure_login_url),
                client_credential=azure_client_secret,
            )
            self._get_token = self._get_token_from_confidential_client
        else:
            if not azure_login_url:
                msg = (
                    "azure_login_url must be provided "
                    "when not using managed identity authentication"
                )
                raise ValueError(msg)
            self._oauth_app = PublicClientApplication(
                azure_client_id,
                authority=str(azure_login_url),
                client_credential=None,
            )
            self._get_token = self._get_token_from_public_client

        self._scope = f"api://{azure_application_id}/.default"
        self._account = None

    def _parse_token(self, msal_response: dict) -> str:
        """
        Parse the OAuth2 token from an MSAL response.

        :param msal_response: The MSAL response containing the token.
        :type msal_response: dict
        :return: The OAuth2 token.
        :rtype: str
        """
        if not msal_response.get("access_token"):
            msg = (
                "Failed to acquire access token: "
                f"{msal_response.get('error', 'Unknown error')}"
            )
            raise RuntimeError(msg)

        return msal_response["access_token"]

    def _get_token_from_public_client(self, *, force_refresh: bool = False) -> str:
        """
        Get an OAuth2 token from a PublicClientApplication.

        :param force_refresh: Whether to force a token refresh.
        :type force_refresh: bool
        :return: The OAuth2 token.
        :rtype: str
        """
        if not isinstance(self._oauth_app, PublicClientApplication):
            msg = "oauth_app must be a PublicClientApplication for this method"
            raise TypeError(msg)

        # Uses msal cache if possible, else interactive login
        result = self._oauth_app.acquire_token_silent(
            scopes=[self._scope],
            account=self._account,
            force_refresh=force_refresh,
        )
        if not result:
            result = self._oauth_app.acquire_token_interactive(scopes=[self._scope])

        access_token = self._parse_token(result)

        # After first login, cache the account for silent token acquisition
        if not self._account and (accounts := self._oauth_app.get_accounts()):
            self._account = accounts[0]

        return access_token

    def _get_token_from_confidential_client(
        self,
        *,
        force_refresh: bool = False,  # noqa: ARG002 MSAL will handle refreshing
    ) -> str:
        """
        Get an OAuth2 token from a ConfidentialClientApplication.

        :param force_refresh: Whether to force a token refresh.
        :type force_refresh: bool
        :return: The OAuth2 token.
        :rtype: str
        """
        if not isinstance(self._oauth_app, ConfidentialClientApplication):
            msg = "oauth_app must be a ConfidentialClientApplication for this method"
            raise TypeError(msg)

        # Uses msal cache if possible, else client credentials flow
        result = self._oauth_app.acquire_token_for_client(scopes=[self._scope])

        return self._parse_token(result)

    def _get_token_from_managed_identity(
        self,
        *,
        force_refresh: bool = False,  # noqa: ARG002 MSAL will handle refreshing
    ) -> str:
        """
        Get an OAuth2 token from a ManagedIdentityClient.

        :param force_refresh: Whether to force a token refresh.
        :type force_refresh: bool
        :return: The OAuth2 token.
        :rtype: str
        """
        if not isinstance(self._oauth_app, ManagedIdentityClient):
            msg = "oauth_app must be a ManagedIdentityClient for this method"
            raise TypeError(msg)

        result = self._oauth_app.acquire_token_for_client(
            resource=self._scope.removesuffix("/.default")
        )

        return self._parse_token(result)

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
                # Force refresh token and retry
                token = self._get_token(force_refresh=True)
                request.headers["Authorization"] = f"Bearer {token}"
                yield request


class OAuthClient:
    """
    Client for interaction with the Destiny API using OAuth2.

    This will apply the provided authentication, usually
    :class:`OAuthMiddleware <libs.sdk.src.destiny_sdk.client.OAuthMiddleware>`,
    to all requests. Some API endpoints are supported directly through methods on this
    class, while others can be accessed through the underlying ``httpx`` client.

    Example usage:

    .. code-block:: python

        from destiny_sdk.client import OAuthClient, OAuthMiddleware

        client = OAuthClient(
            base_url="https://destiny-repository.example.com",
            auth=OAuthMiddleware(...),
        )

        # Supported method
        response = client.search(query="example")

        # Unsupported method, use underlying httpx client
        response = client.get_client().get("/system/healthcheck/")
    """

    def __init__(
        self,
        base_url: HttpUrl | str,
        auth: httpx.Auth | None = None,
        timeout: int = 10,
    ) -> None:
        """
        Initialize the client.

        :param base_url: The base URL for the Destiny Repository API.
        :type base_url: HttpUrl
        :param auth: The middleware for authentication. If not provided, only
            unauthenticated requests can be made. This should almost always be an
            instance of ``OAuthMiddleware``, unless you need to create a custom auth
            class.
        :type auth: httpx.Auth | None
        :param timeout: The timeout for requests, in seconds. Defaults to 10 seconds.
        :type timeout: int
        """
        self._client = httpx.Client(
            base_url=str(base_url).removesuffix("/").removesuffix("/v1") + "/v1",
            headers={
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
            timeout=timeout,
        )

        if auth:
            self._client.auth = auth

    def _raise_for_status(self, response: httpx.Response) -> None:
        """
        Raise an error if the response status is not successful.

        :param response: The HTTP response to check.
        :type response: httpx.Response
        :raises httpx.HTTPStatusError: If the response status is not successful.
        """
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            msg = (
                f"Error response {exc.response.status_code} from "
                f"{exc.request.url}: {exc.response.text}"
            )
            raise httpx.HTTPStatusError(
                msg, request=exc.request, response=exc.response
            ) from exc

    def search(  # noqa: PLR0913
        self,
        query: str,
        start_year: int | None = None,
        end_year: int | None = None,
        annotations: list[str | AnnotationFilter] | None = None,
        sort: str | None = None,
        page: int = 1,
        timeout: int | None = None,
    ) -> ReferenceSearchResult:
        """
        Send a search request to the Destiny Repository API.

        See also: :ref:`search-procedure`.

        :param query: The search query string.
        :type query: str
        :param start_year: The start year for filtering results.
        :type start_year: int | None
        :param end_year: The end year for filtering results.
        :type end_year: int | None
        :param annotations: A list of annotation filters to apply.
        :type annotations: list[str | libs.sdk.src.destiny_sdk.search.AnnotationFilter] | None
        :param sort: The sort order for the results.
        :type sort: str | None
        :param page: The page number of results to retrieve.
        :type page: int
        :param timeout: The timeout for the request, in seconds. If provided, this will override
        the client timeout.
        :type timeout: int | None
        :return: The response from the API.
        :rtype: libs.sdk.src.destiny_sdk.references.ReferenceSearchResult
        """  # noqa: E501
        params = {"q": query, "page": page}
        if start_year:
            params["start_year"] = start_year
        if end_year:
            params["end_year"] = end_year
        if annotations:
            params["annotation"] = [str(annotation) for annotation in annotations]
        if sort:
            params["sort"] = sort
        response = self._client.get(
            "/references/search/",
            params=params,
            timeout=timeout or httpx.USE_CLIENT_DEFAULT,
        )
        self._raise_for_status(response)
        return ReferenceSearchResult.model_validate(response.json())

    def lookup(
        self,
        identifiers: list[str | IdentifierLookup],
        timeout: int | None = None,
    ) -> list[Reference]:
        """
        Lookup references by identifiers.

        See also: :ref:`lookup-procedure`.

        :param identifiers: The identifiers to look up.
        :type identifiers: list[str | libs.sdk.src.destiny_sdk.identifiers.IdentifierLookup]
        :param timeout: The timeout for the request, in seconds. If provided, this will override
        the client timeout.
        :type timeout: int | None
        :return: The list of references matching the identifiers.
        :rtype: list[libs.sdk.src.destiny_sdk.references.Reference]
        """  # noqa: E501
        response = self._client.get(
            "/references/",
            params={
                "identifier": ",".join([str(identifier) for identifier in identifiers])
            },
            timeout=timeout or httpx.USE_CLIENT_DEFAULT,
        )
        self._raise_for_status(response)
        return TypeAdapter(list[Reference]).validate_python(response.json())

    def get_client(self) -> httpx.Client:
        """
        Get the underlying ``httpx`` client.

        This can be used to make custom requests not covered by the SDK methods.

        :return: The underlying ``httpx`` client with authentication attached.
        :rtype: `httpx.Client <https://www.python-httpx.org/advanced/clients/>`_
        """
        return self._client
