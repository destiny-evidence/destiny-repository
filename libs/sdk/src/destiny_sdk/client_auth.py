"""Send authenticated requests to Destiny Repository."""

from collections.abc import Generator
from enum import StrEnum
from typing import Annotated, Literal

import httpx
import msal
from pydantic import BaseModel, Field, HttpUrl

from destiny_sdk.robots import RobotResult


class AuthenticationType(StrEnum):
    """
    The type of authentication to use.

    **Allowed values**:
    - `access_token`: Authenticate with an access token
    - `managed_identity`: Authenticate with a managed identity
    """

    ACCESS_TOKEN = "access_token"  # noqa: S105
    MANAGED_IDENTITY = "managed_identity"


class _ClientAuthenticationMethod(BaseModel):
    """Force the implementation of a get_token method on Authentication subclasses."""

    def get_token(self) -> str:
        """
        Return an access token.

        :raises NotImplementedError: raises error if this function is not implemneted.
        :return: a JWT.
        :rtype: str
        """
        msg = "Authentication methods must implement get_token()."
        raise NotImplementedError(msg)


class ManagedIdentityAuthentication(_ClientAuthenticationMethod):
    """Model for managed identiy authentication."""

    azure_application_url: str = Field(pattern="api://*")
    azure_client_id: str
    authentication_type: Literal[AuthenticationType.MANAGED_IDENTITY] = (
        AuthenticationType.MANAGED_IDENTITY
    )

    def get_token(self) -> str:
        """
        Get an access token using a the managed identity.

        :return: a JWT.
        :rtype: str
        """
        auth_client = msal.ManagedIdentityClient(
            managed_identity=msal.UserAssignedManagedIdentity(
                client_id=self.azure_client_id
            ),
            http_client=httpx.Client(),
        )

        result = auth_client.acquire_token_for_client(
            resource=self.azure_application_url
        )

        return result["access_token"]


class AccessTokenAuthentication(_ClientAuthenticationMethod):
    """Model for access token authentication."""

    access_token: str
    authentication_type: Literal[AuthenticationType.ACCESS_TOKEN] = (
        AuthenticationType.ACCESS_TOKEN
    )

    def get_token(self) -> str:
        """
        Get an access token.

        :return: a JWT.
        :rtype: str
        """
        return self.access_token


ClientAuthenticationMethod = Annotated[
    ManagedIdentityAuthentication | AccessTokenAuthentication,
    Field(discriminator="authentication_type"),
]


class DestinyAuth(httpx.Auth):
    """
    Custom httpx.Auth to inject Bearer token from ClientAuthenticationMethod.

    Automatically refreshes token on expiration.
    """

    def __init__(self, auth_method: ClientAuthenticationMethod) -> None:
        """Initialize DestinyAuth with a client authentication method."""
        self._auth_method = auth_method
        self._token: str | None = None

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        """Auth flow called by httpx to add token to a request."""
        # TODO (Jack): rework this to check token expiry instead of retrying call
        # https://github.com/destiny-evidence/destiny-repository/issues/101
        if not self._token:
            self._token = self._auth_method.get_token()
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == httpx.codes.UNAUTHORIZED:
            try:
                detail = response.json().get("detail", "")
            except ValueError:
                detail = ""

            if detail == "Token is expired.":
                # Refresh token and retry
                self._token = self._auth_method.get_token()
                request.headers["Authorization"] = f"Bearer {self._token}"
                yield request


def send_robot_result(
    url: HttpUrl, auth_method: ClientAuthenticationMethod, robot_result: RobotResult
) -> None:
    """
    Send a RobotResult to destiny repository.

    Generates an JWT using the provided ClientAuthenticationMethod.


    :param url: The url to send the robot result to.
    :type url: HttpUrl
    :param auth_method: The authentication method to generate a token with.
    :type auth_method: ClientAuthenticationMethod
    :param robot_result: The Robot Result to send
    :type robot_result: RobotResult
    """
    auth = DestinyAuth(auth_method)
    with httpx.Client(auth=auth) as client:
        client.post(
            str(url),
            json=robot_result.model_dump(mode="json"),
        )
