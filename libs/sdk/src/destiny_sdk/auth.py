"""HMAC authentication assistance methods."""

import hashlib
import hmac
import time
from typing import Protocol, Self
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import UUID4, BaseModel

FIVE_MINUTES = 60 * 5


class AuthException(HTTPException):
    """
    An exception related to HTTP authentication.

    Raised by implementations of the AuthMethod protocol.

    .. code-block:: python

        raise AuthException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to parse authentication token.",
        )

    """


def create_signature(
    secret_key: str, request_body: bytes, client_id: UUID4, timestamp: float
) -> str:
    """
    Create an HMAC signature using SHA256.

    :param secret_key: secret key with which to encrypt message
    :type secret_key: bytes
    :param request_body: request body to be encrypted
    :type request_body: bytes
    :param client_id: client id to include in hmac
    :type: UUID4
    :param timestamp: timestamp for when the request is sent
    :type: float
    :return: encrypted hexdigest of the request body with the secret key
    :rtype: str
    """
    timestamp_bytes = f"{timestamp}".encode()
    signature_components = b":".join([request_body, client_id.bytes, timestamp_bytes])
    return hmac.new(
        secret_key.encode(), signature_components, hashlib.sha256
    ).hexdigest()


class HMACAuthorizationHeaders(BaseModel):
    """
    The HTTP authorization headers required for HMAC authentication.

    Expects the following headers to be present in the request

    - Authorization: Signature [request signature]
    - X-Client-Id: [UUID]
    - X-Request-Timestamp: [float]
    """

    signature: str
    client_id: UUID4
    timestamp: float

    @classmethod
    def from_request(cls, request: Request) -> Self:
        """
        Get the required headers for HMAC authentication.

        :param request: The incoming request
        :type request: Request
        :raises AuthException: Authorization header is missing
        :raises AuthException: Authorization type not supported
        :raises AuthException: X-Client-Id header is missing
        :raises AuthException: Client id format is invalid
        :raises AuthException: X-Request-Timestamp header is missing
        :raises AuthException: Request timestamp has expired
        :return: Header values necessary for authenticating the request
        :rtype: HMACAuthorizationHeaders
        """
        signature_header = request.headers.get("Authorization")

        if not signature_header:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing.",
            )

        scheme, _, signature = signature_header.partition(" ")

        if scheme != "Signature":
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization type not supported.",
            )

        client_id = request.headers.get("X-Client-Id")

        if not client_id:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Client-Id header missing",
            )

        try:
            UUID(client_id)
        except (ValueError, TypeError) as exc:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid format for client id, expected UUID4.",
            ) from exc

        timestamp = request.headers.get("X-Request-Timestamp")

        if not timestamp:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Request-Timestamp header missing",
            )

        if (time.time() - float(timestamp)) > FIVE_MINUTES:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp has expired.",
            )

        return cls(signature=signature, client_id=client_id, timestamp=timestamp)


class HMACAuthMethod(Protocol):
    """
    Protocol for HMAC auth methods, enforcing the implmentation of __call__().

    This allows FastAPI to call class instances as depenedencies in FastAPI routes,
    see https://fastapi.tiangolo.com/advanced/advanced-dependencies

        .. code-block:: python

            auth = HMACAuthMethod()

            router = APIRouter(
                prefix="/robots", tags=["robot"], dependencies=[Depends(auth)]
            )
    """

    async def __call__(self, request: Request) -> bool:
        """
        Callable interface to allow use as a dependency.

        :param request: The request to verify
        :type request: Request
        :raises NotImplementedError: __call__() method has not been implemented.
        :return: True if authorization is successful.
        :rtype: bool
        """
        raise NotImplementedError


class HMACAuth(HMACAuthMethod):
    """Adds HMAC auth when used as a router or endpoint dependency."""

    def __init__(self, secret_key: str) -> None:
        """Initialise HMAC auth with a given secret key."""
        self.secret_key = secret_key

    async def __call__(self, request: Request) -> bool:
        """Perform Authorization check."""
        auth_headers = HMACAuthorizationHeaders.from_request(request)
        request_body = await request.body()
        expected_signature = create_signature(
            self.secret_key,
            request_body,
            auth_headers.client_id,
            auth_headers.timestamp,
        )

        if not hmac.compare_digest(auth_headers.signature, expected_signature):
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature is invalid."
            )

        return True


class BypassHMACAuth(HMACAuthMethod):
    """
    A fake auth class that will always respond successfully.

    Intended for use in local environments and for testing.

    Not for production use!
    """

    async def __call__(
        self,
        request: Request,  # noqa: ARG002
    ) -> bool:
        """Bypass Authorization check."""
        return True
