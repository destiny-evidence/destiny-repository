"""Client for interaction with the Destiny API."""

from collections.abc import Generator

import httpx
from httpx import codes
from pydantic import HttpUrl

from destiny_sdk.client_auth import ClientAuthenticationMethod
from destiny_sdk.robots import (
    BatchEnhancementRequestRead,
    BatchRobotResult,
    EnhancementRequestRead,
    RobotResult,
)


class _DestinyAuth(httpx.Auth):
    """
    Custom httpx.Auth to inject Bearer token from ClientAuthenticationMethod.

    Automatically refreshes token on expiration.
    """

    def __init__(self, auth_method: ClientAuthenticationMethod) -> None:
        self._auth_method = auth_method
        self._token = None

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        if not self._token:
            self._token = self._auth_method.get_token()
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == codes.UNAUTHORIZED:
            try:
                detail = response.json().get("detail", "")
            except ValueError:
                detail = ""

            if detail == "Token is expired.":
                # Refresh token and retry
                self._token = self._auth_method.get_token()
                request.headers["Authorization"] = f"Bearer {self._token}"
                yield request


class Client:
    """
    Client for interaction with the Destiny API.

    Current implementation only supports robot results.
    """

    def __init__(
        self, base_url: HttpUrl, auth_method: ClientAuthenticationMethod
    ) -> None:
        """
        Initialize the client.

        :param base_url: The base URL for the Destiny Repository API.
        :type base_url: HttpUrl
        :param auth_method: The authentication method to use for the API.
        :type auth_method: ClientAuthenticationMethod
        """
        self.base_url = base_url
        self.auth_method = auth_method
        self.session = httpx.Client(
            base_url=base_url,
            headers={"Content-Type": "application/json"},
            auth=_DestinyAuth(auth_method),
        )

    def send_robot_result(self, robot_result: RobotResult) -> EnhancementRequestRead:
        """
        Send a RobotResult to destiny repository.

        Generates an JWT using the provided ClientAuthenticationMethod.

        :param robot_result: The Robot Result to send
        :type robot_result: RobotResult
        :return: The EnhancementRequestRead object from the response.
        :rtype: EnhancementRequestRead
        """
        response = self.session.post(
            "/robot/enhancement/single/",
            json=robot_result.model_dump(mode="json"),
        )
        response.raise_for_status()
        return EnhancementRequestRead.model_validate(response.json())

    def send_batch_robot_result(
        self, batch_robot_result: BatchRobotResult
    ) -> BatchEnhancementRequestRead:
        """
        Send a BatchRobotResult to destiny repository.

        Generates an JWT using the provided ClientAuthenticationMethod.

        :param batch_robot_result: The Batch Robot Result to send
        :type batch_robot_result: BatchRobotResult
        :return: The BatchEnhancementRequestRead object from the response.
        :rtype: BatchEnhancementRequestRead
        """
        response = self.session.post(
            "/robot/enhancement/batch/",
            json=batch_robot_result.model_dump(mode="json"),
        )
        response.raise_for_status()
        return BatchEnhancementRequestRead.model_validate(response.json())
