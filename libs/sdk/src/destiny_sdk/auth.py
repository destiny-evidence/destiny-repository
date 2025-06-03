"""HMAC authentication assistance methods."""

import hmac
from typing import Protocol, Self
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import UUID4, BaseModel

from .client import create_signature


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


class HMACAuthorizationHeaders(BaseModel):
    """
    The HTTP authorization headers required for HMAC authentication.

    ```
    Authorization: Signature [ADD THIS]
    X-Client-Id: [ADD THIS]
    ```

    """

    signature: str
    client_id: UUID4
    # Add timestamp later

    @classmethod
    def get_hmac_headers(cls, request: Request) -> Self:
        """
        Get the required headers for HMAC authentication.

        :param request: The incoming request
        :type request: Request
        :raises AuthException: Authorization header is missing
        :raises AuthException: Authorization type not supported
        :raises AuthException: X-Client-Id header is missing
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

        return cls(signature=signature, client_id=client_id)


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
        auth_headers = HMACAuthorizationHeaders.get_hmac_headers(request)
        request_body = await request.body()
        expected_signature = create_signature(
            self.secret_key, request_body, auth_headers.client_id
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
