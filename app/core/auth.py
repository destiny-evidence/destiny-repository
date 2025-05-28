"""Tools for authorising requests."""

import hashlib
import hmac
from enum import StrEnum
from typing import Protocol

from destiny_sdk.auth import AuthMethod, AzureJwtAuth, SuccessAuth
from fastapi import HTTPException, Request, status

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


async def create_signature(request: Request) -> str:
    """Create an HMAC signature."""
    body = await request.body()
    return hmac.new(SECRET_KEY, body, hashlib.sha256).hexdigest()


class HMACAuthMethod(Protocol):
    """
    Protocol for auth methods, enforcing the implmentation of __call__().

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
        expected_signature = await create_signature(request)

        if request.headers.get("Authorization") != f"Signature {expected_signature}":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authorized"
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
