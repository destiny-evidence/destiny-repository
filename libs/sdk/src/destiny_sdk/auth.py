"""HMAC authentication assistance methods."""

import hmac
from typing import Protocol

from fastapi import HTTPException, Request, status

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

    async def __call__(
        self,
        request: Request,
    ) -> bool:
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
        signature_header = request.headers.get("Authorization")

        if not signature_header:
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization Signature header missing.",
            )

        # Need to improve this to handle malformed headers gracefully
        scheme, _, signature = signature_header.partition(" ")

        if scheme != "Signature":
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization type not supported.",
            )

        request_body = await request.body()
        expected_signature = create_signature(self.secret_key, request_body)

        if not hmac.compare_digest(signature, expected_signature):
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

    async def __call__(self, request: Request) -> bool:  # noqa: ARG002
        """Bypass Authorization check."""
        return True
