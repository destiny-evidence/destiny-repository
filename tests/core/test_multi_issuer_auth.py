"""Test multi-issuer JWT authentication (Azure AD + Keycloak)."""

import datetime
import re
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request, status
from jose import jwt as jose_jwt
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import RSAKey
from pytest_httpx import HTTPXMock

from app.api.auth import (
    AuthRole,
    AuthScope,
    AzureJwtAuth,
    KeycloakJwtAuth,
    MultiIssuerJwtAuth,
    _build_jwt_auth,
)
from app.api.auth import settings as auth_settings

# Reuse the same RSA key pair from conftest.py / test_keycloak_auth.py
_test_private_key = {
    "kty": "RSA",
    "kid": "test-key-id",
    "use": "sig",
    "alg": "RS256",
    "n": "kKDUcNhINFIRjuzK2pW1dYGF0iJjmy9Ux15TJwSEX7MeKplHp58HnM_--ZHRj4gEp-Gq9l7wNowdJEO72nITfnjQpyroSIimAY0hxMgv96v7dYS1mYLcPASYenXNWYXA0IrK5ZRb_6NacsA_yVOoeWDglwzEZFkgmyXpi2pI988FY8nDMAlC7KD4IlSTeOakW1zkdd6eQY7CeThIEGlL826vlR2aziAKRtiKBzgfY8Y50USoa7zWRfYqay9A_e_Y_lvj9vPa0fl9MKZpqbHEsN7MrNpMOpuJ6vajtp7JL12IBcgLH9Q80on73Isj6RYc3zS5_SllXS7NbxfJ0jZ7IQ",  # noqa: E501
    "e": "AQAB",
    "d": "P-w1uSJ-11EmnYsfJXlh2GvE39l_OMm0qOGR0v72Gu4p-R4CQ53QWYi840WF3_B4TlM5oubXOOS4xJyDXMtqvk1bu2cFf3mWFb1xHW51dPw4ifp74TurZ4OIeSez-Utaq1GM1-e4ucZTZcB-8Nbe8bbVzS1BaDDUbn5VON9jHNNda5jQQojcVNF_TRyREJ-kizz3CyveIjmeS6Lb9regIYfAZnrKCiEvhv1m6zhvvqxViz7nzp8D-Es2nrksqWUO-Eh8O9UmeqcHJi32V5PyTTxHP2IG5-x18Bn_cX7_ntZ8a9ollTjf6PoUZMGz_Dsybu7QfQkadgr0sEPODQ7wgQ",  # noqa: E501
    "p": "-X2N5eWnp5Wr6rfhLuC30mKIoG1KXCjlZQMyP6QOCayMxhrhUM2ZeHtcl7ExMX0vRr2auQtWYlfPsnHEEbOCehehdoKWgZouCX_CLvBV484T_EIIvcnHp6fCJYpOnodbl6R7kT9if3wI672CAARdiMXmfj94xVj0pYyQZ_Mag5k",  # noqa: E501
    "q": "lGbb-VSNfQdCFTki3ClQPCk2YdV4Vh9PVk8Sx9_oTheDGWCKuuhVjqooKedPmqMw1X23GCQwV3pqbKUEonY7BsryUG2MFLCzxJm-c45eWqmR-1rhnwnxHvlopAoSL2CPh4qVqMbGXJ3hJ5roU8KmLAop_DcS7NfvwGG4YInHaMk",  # noqa: E501
    "dp": "P90r3ZWT_QoLH-JB-kX7yBcA8lAHoN-3GMxgqHnOPhu1TWDEHHMEvhqV8R6igRCScYFHgeatDi98Myl8DyvsUmSKKFP1Que8sSHLC0jqM44k_4XHxw1H1lrTD9j_lwT_JSotl1iqVgfiILY5-NclOkWuYtLMj3fd6CK7NGC-gME",  # noqa: E501
    "dq": "gg0WL416pRwsPF8i_p-x8dcIEnq6B3dO1stbIRBHC9CtEhs52IxtFiZmJjrQ1yq2TBHs19o3ByJ_i5Cd3CYSmmRWMEegYC1ujRdTAP--DmPWS9mcKfzTcxqNKlytDRnpDpZTi2IPSfEN9OBbQ7QsXiHWI3K8QhUGxaidpPR5bYk",  # noqa: E501
    "qi": "PoZSlTkB3dVl4mp24kTx4EK4YrT-c7lclsUBArdWt6WhVPCKMjWT1NZ6-sTw4TmWb7a-lOCqXLkfBVMzLkfpR3wp-J_TNfnb9PGP8-cTIE0FAEG9Kpc7tDNj1VhqU1Bl7Yse-Sp1u3vRvSqZvouNfSmTR00_648PrZegTDLZV2A",  # noqa: E501
}

FAKE_KEYCLOAK_URL = "http://localhost:8080"
FAKE_KEYCLOAK_REALM = "destiny"
FAKE_KEYCLOAK_CLIENT_ID = "destiny-repository-client"
FAKE_KEYCLOAK_ISSUER = f"{FAKE_KEYCLOAK_URL}/realms/{FAKE_KEYCLOAK_REALM}"

FAKE_AZURE_APP_ID = "test_application_id"
FAKE_AZURE_LOGIN_URL = "https://login.microsoftonline.com"
FAKE_AZURE_ISSUER = f"{FAKE_AZURE_LOGIN_URL}/v2.0"


@pytest.fixture
def fake_public_key() -> dict[str, str]:
    """Return the public portion of the test key pair."""
    return {
        "kty": _test_private_key["kty"],
        "kid": _test_private_key["kid"],
        "use": _test_private_key["use"],
        "alg": _test_private_key["alg"],
        "n": _test_private_key["n"],
        "e": _test_private_key["e"],
    }


@pytest.fixture
def azure_auth() -> AzureJwtAuth:
    """Create an AzureJwtAuth instance for testing."""
    return AzureJwtAuth(
        application_id=FAKE_AZURE_APP_ID,
        scope=AuthScope.REFERENCE_READER,
        role=AuthRole.REFERENCE_READER,
    )


@pytest.fixture
def keycloak_auth() -> KeycloakJwtAuth:
    """Create a KeycloakJwtAuth instance for testing."""
    return KeycloakJwtAuth(
        keycloak_url=FAKE_KEYCLOAK_URL,
        realm=FAKE_KEYCLOAK_REALM,
        client_id=FAKE_KEYCLOAK_CLIENT_ID,
        scope=AuthScope.REFERENCE_READER,
        role=AuthRole.REFERENCE_READER,
    )


@pytest.fixture
def multi_issuer_auth(
    azure_auth: AzureJwtAuth,
    keycloak_auth: KeycloakJwtAuth,
) -> MultiIssuerJwtAuth:
    """Create a MultiIssuerJwtAuth instance for testing."""
    return MultiIssuerJwtAuth(
        azure_auth=azure_auth,
        keycloak_auth=keycloak_auth,
    )


@pytest.fixture
def fake_request() -> Request:
    """Create a fake request for testing."""
    return Request(scope={"type": "http", "path": "/test"})


def _generate_azure_token(
    user_payload: dict | None = None,
    scope: AuthScope | None = None,
    role: AuthRole | None = None,
) -> str:
    """Generate a fake Azure AD token."""
    payload: dict = {
        "sub": "azure-test-user",
        "iat": datetime.datetime.now(datetime.UTC),
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
        "aud": FAKE_AZURE_APP_ID,
        "iss": FAKE_AZURE_ISSUER,
    }
    if user_payload:
        payload.update(user_payload)
    if scope:
        payload["scp"] = scope
    elif role:
        payload["roles"] = [role]
    return jose_jwt.encode(
        payload,
        _test_private_key,
        algorithm="RS256",
        headers={"kid": _test_private_key["kid"]},
    )


def _generate_keycloak_token(
    user_payload: dict | None = None,
    scope: str | None = None,
    role: str | None = None,
) -> str:
    """Generate a fake Keycloak token."""
    now = datetime.datetime.now(datetime.UTC)
    payload: dict = {
        "sub": "keycloak-test-user",
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(minutes=10)).timestamp()),
        "aud": FAKE_KEYCLOAK_CLIENT_ID,
        "iss": FAKE_KEYCLOAK_ISSUER,
        "azp": "destiny-auth-client",
        "typ": "Bearer",
    }
    if user_payload:
        payload.update(user_payload)
    if scope:
        payload["scope"] = f"openid profile email {scope}"
    if role:
        payload["realm_access"] = {"roles": [role]}
    private_key = RSAKey.import_key(_test_private_key)
    header = {"alg": "RS256", "kid": _test_private_key["kid"]}
    return joserfc_jwt.encode(header, payload, private_key)


@pytest.fixture
def stub_azure_jwks(httpx_mock: HTTPXMock, fake_public_key: dict) -> None:
    """Stub JWKS response for Azure AD."""
    escaped_url = re.escape(FAKE_AZURE_LOGIN_URL)
    httpx_mock.add_response(
        url=re.compile(rf"{escaped_url}/"),
        json={"keys": [fake_public_key]},
    )


@pytest.fixture
def stub_keycloak_jwks(httpx_mock: HTTPXMock, fake_public_key: dict) -> None:
    """Stub JWKS response for Keycloak."""
    httpx_mock.add_response(
        url=f"{FAKE_KEYCLOAK_URL}/realms/{FAKE_KEYCLOAK_REALM}"
        "/protocol/openid-connect/certs",
        json={"keys": [fake_public_key]},
    )


class TestMultiIssuerAuth:
    """End-to-end tests through MultiIssuerJwtAuth.__call__."""

    async def test_azure_token_accepted(
        self,
        multi_issuer_auth: MultiIssuerJwtAuth,
        fake_request: Request,
        stub_azure_jwks: None,  # noqa: ARG002
    ) -> None:
        """Azure token with correct scope is accepted."""
        token = _generate_azure_token(scope=AuthScope.REFERENCE_READER)
        credentials = Mock()
        credentials.credentials = token
        assert await multi_issuer_auth(fake_request, credentials) is True

    async def test_keycloak_token_accepted(
        self,
        multi_issuer_auth: MultiIssuerJwtAuth,
        fake_request: Request,
        stub_keycloak_jwks: None,  # noqa: ARG002
    ) -> None:
        """Keycloak token with correct scope is accepted."""
        token = _generate_keycloak_token(scope=AuthScope.REFERENCE_READER)
        credentials = Mock()
        credentials.credentials = token
        assert await multi_issuer_auth(fake_request, credentials) is True

    async def test_unknown_issuer_token(
        self,
        multi_issuer_auth: MultiIssuerJwtAuth,
        fake_request: Request,
    ) -> None:
        """Token from unknown issuer is rejected with 401."""
        token = _generate_azure_token(
            user_payload={"iss": "https://unknown.example.com"},
            scope=AuthScope.REFERENCE_READER,
        )
        credentials = Mock()
        credentials.credentials = token
        with pytest.raises(HTTPException) as exc_info:
            await multi_issuer_auth(fake_request, credentials)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_token(
        self,
        multi_issuer_auth: MultiIssuerJwtAuth,
        fake_request: Request,
    ) -> None:
        """Malformed token is rejected with 401."""
        credentials = Mock()
        credentials.credentials = "garbage"
        with pytest.raises(HTTPException) as exc_info:
            await multi_issuer_auth(fake_request, credentials)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestBuildJwtAuth:
    """Tests for _build_jwt_auth with auth_provider='both'."""

    def test_returns_multi_issuer_auth(self) -> None:
        """auth_provider='both' returns MultiIssuerJwtAuth."""
        original_provider = auth_settings.auth_provider
        original_url = auth_settings.keycloak_url
        original_client = auth_settings.keycloak_client_id
        try:
            auth_settings.auth_provider = "both"
            auth_settings.keycloak_url = FAKE_KEYCLOAK_URL
            auth_settings.keycloak_client_id = FAKE_KEYCLOAK_CLIENT_ID

            result = _build_jwt_auth(
                FAKE_AZURE_APP_ID,
                AuthScope.REFERENCE_READER,
                AuthRole.REFERENCE_READER,
            )
            assert isinstance(result, MultiIssuerJwtAuth)
        finally:
            auth_settings.auth_provider = original_provider
            auth_settings.keycloak_url = original_url
            auth_settings.keycloak_client_id = original_client
