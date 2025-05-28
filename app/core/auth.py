"""Tools for authorising requests."""

import hashlib
import hmac
from enum import StrEnum
from typing import Protocol

from destiny_sdk.auth import AuthException, AuthMethod, AzureJwtAuth, SuccessAuth
from fastapi import Request, status

from app.core.config import Environment, get_settings

CACHE_TTL = 60 * 60 * 24  # 24 hours

settings = get_settings()


class AuthScopes(StrEnum):
    """Enum describing the available auth scopes that we understand."""

    IMPORT = "import"
    REFERENCE_READER = "reference.reader"
    REFERENCE_WRITER = "reference.writer"
    ROBOT = "robot"


def choose_auth_strategy(
    environment: Environment,
    tenant_id: str,
    application_id: str,
    auth_scope: AuthScopes,
) -> AuthMethod:
    """Choose a strategy for our authorization."""
    if environment in (Environment.LOCAL, Environment.TEST):
        return SuccessAuth()

    return AzureJwtAuth(
        tenant_id=tenant_id,
        application_id=application_id,
        scope=auth_scope,
    )


# To be replaced with the secret key for each robot
SECRET_KEY = b"dlfskdfhgk8ei346oiehslkdf"


def create_signature(secret_key: bytes, request_body: bytes) -> str:
    """
    Create an HMAC signature using SHA256.

    :param secret_key: secret key with which to encrypt message
    :type secret_key: bytes
    :param request_body: request body to be encrypted
    :type request_body: bytes
    :return: encrypted hexdigest of the request body with the secret key
    :rtype: str
    """
    return hmac.new(secret_key, request_body, hashlib.sha256).hexdigest()


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
        expected_signature = create_signature(SECRET_KEY, request_body)

        if not hmac.compare_digest(signature, expected_signature):
            raise AuthException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature is invalid."
            )

        return True


class BypassHMACAuth:
    """
    A fake auth class that will always respond successfully.

    Intended for use in local environments and for testing.

    Not for production use!
    """

    async def __call__(self, request: Request) -> bool:  # noqa: ARG002
        """Bypass Authorization check."""
        return True


def choose_hmac_auth_strategy() -> HMACAuthMethod:
    """Choose an HMAC auth method."""
    if settings.env in (Environment.LOCAL, Environment.TEST):
        return BypassHMACAuth()

    return HMACAuth()
