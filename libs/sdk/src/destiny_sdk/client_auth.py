"""Helper methods for sending authenticated requets †o destiny repository."""

from enum import StrEnum
from typing import Annotated, Literal

import httpx
import msal
from pydantic import UUID4, BaseModel, Field

from .robots import RobotResult


class AuthenticationType(StrEnum):
    """
    The type of authentication to use.

    **Allowed values**:
    - `access_token`: Authenticate with an access token
    - `managed_identity`: Authenticate with a managed identity
    """

    ACCESS_TOKEN = "access_token"  # noqa: S105
    MANAGED_IDENTITY = "managed_identity"


class ManagedIdentityAuthentication(BaseModel):
    """Model for managed identiy authentication."""

    azure_application_url: str = Field(pattern="api//*")
    azure_client_id: UUID4
    authentication_type: Literal[AuthenticationType.MANAGED_IDENTITY] = (
        AuthenticationType.MANAGED_IDENTITY
    )

    def get_token(self) -> str:
        """Get an access token."""
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


class AccessTokenAuthentication(BaseModel):
    """Model for access token authentication."""

    access_token: str
    authentication_type: Literal[AuthenticationType.ACCESS_TOKEN] = (
        AuthenticationType.ACCESS_TOKEN
    )

    def get_token(self) -> str:
        """Get an access token."""
        return self.access_token


AuthenticationMethod = Annotated[
    ManagedIdentityAuthentication | AccessTokenAuthentication,
    Field(discriminator="authentication_type"),
]


def send_robot_result(
    url: str, auth_method: AuthenticationMethod, robot_result: RobotResult
) -> None:
    """Send a RobotResult to destiny repository with access token authenticaiton."""
    token = auth_method.get_token()
    with httpx.Client() as client:
        client.post(
            str(url),
            headers={"Authorization": f"Bearer {token}"},
            json=robot_result.model_dump(mode="json"),
        )
