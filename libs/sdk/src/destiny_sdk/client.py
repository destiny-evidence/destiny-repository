"""Send authenticated requests to Destiny Repository."""

import time
from collections.abc import Generator

import httpx
from pydantic import UUID4, HttpUrl

from destiny_sdk.robots import (
    EnhancementRequestRead,
    RobotEnhancementBatch,
    RobotEnhancementBatchRead,
    RobotEnhancementBatchResult,
    RobotResult,
)

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


class Client:
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
        self, robot_id: UUID4, limit: int = 10, timeout: int = 60
    ) -> RobotEnhancementBatch | None:
        """
        Poll for a robot enhancement batch.

        Signs the request with the client's secret key.

        :param robot_id: The ID of the robot to poll for
        :type robot_id: UUID4
        :param limit: The maximum number of pending enhancements to return
        :type limit: int
        :return: The RobotEnhancementBatch object from the response, or None if no
            batches available
        :rtype: destiny_sdk.robots.RobotEnhancementBatch | None
        """
        response = self.session.post(
            "/robot-enhancement-batches/",
            params={"robot_id": str(robot_id), "limit": limit},
            timeout=timeout,
        )
        # HTTP 204 No Content indicates no batches available
        if response.status_code == httpx.codes.NO_CONTENT:
            return None

        response.raise_for_status()
        return RobotEnhancementBatch.model_validate(response.json())
