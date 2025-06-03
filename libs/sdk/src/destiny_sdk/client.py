"""Send authenticated requests to Destiny Repository."""

import hashlib
import hmac
from collections.abc import Generator

import httpx
from pydantic import UUID4, HttpUrl

from destiny_sdk.robots import (
    BatchEnhancementRequestRead,
    BatchRobotResult,
    EnhancementRequestRead,
    RobotResult,
)


def create_signature(secret_key: str, request_body: bytes, client_id: str) -> str:
    """
    Create an HMAC signature using SHA256.

    :param secret_key: secret key with which to encrypt message
    :type secret_key: bytes
    :param request_body: request body to be encrypted
    :type request_body: bytes
    :return: encrypted hexdigest of the request body with the secret key
    :rtype: str
    """
    signature_components = f"{request_body!r}:{client_id}"
    return hmac.new(
        secret_key.encode(), signature_components.encode(), hashlib.sha256
    ).hexdigest()


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
        signature = create_signature(
            self.secret_key, request.content, str(self.client_id)
        )
        request.headers["Authorization"] = f"Signature {signature}"
        request.headers["X-Client-Id"] = f"{self.client_id}"
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
            base_url=str(base_url),
            headers={"Content-Type": "application/json"},
            auth=HMACSigningAuth(secret_key=secret_key, client_id=client_id),
        )

    def send_robot_result(self, robot_result: RobotResult) -> EnhancementRequestRead:
        """
        Send a RobotResult to destiny repository.

        Signs the request with the client's secret key.

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

        Signs the request with the client's secret key.

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
