"""Test Keycloak JWT authentication."""

import datetime
from enum import StrEnum
from typing import Protocol
from unittest.mock import Mock

import pytest
from authlib.jose import JsonWebKey
from authlib.jose import jwt as authlib_jwt
from fastapi import HTTPException, Request, status
from pytest_httpx import HTTPXMock

from app.api.auth import KeycloakJwtAuth


class FakeAuthScopes(StrEnum):
    """Fake authentication scopes used for testing."""

    READ_ALL = "reference.reader.all"


class FakeAuthRoles(StrEnum):
    """Fake authentication roles used for testing."""

    READER = "reference.reader"


class TokenGenerator(Protocol):
    """Protocol for the generate_keycloak_token fixture."""

    def __call__(
        self,
        user_payload: dict | None = None,
        scope: str | None = None,
        role: str | None = None,
    ) -> str:
        """Generate a fake Keycloak token for testing."""
        ...


# Test RSA key pair for signing tokens
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


@pytest.fixture
def fake_keycloak_url() -> str:
    """Return a fake Keycloak URL for testing."""
    return "http://localhost:8080"


@pytest.fixture
def fake_realm() -> str:
    """Return a fake realm name for testing."""
    return "destiny"


@pytest.fixture
def fake_client_id() -> str:
    """Return a fake client ID for testing."""
    return "destiny-repository-client"


@pytest.fixture
def fake_public_key() -> dict[str, str]:
    """Return the public key portion of the test key pair."""
    return {
        "kty": _test_private_key["kty"],
        "kid": _test_private_key["kid"],
        "use": _test_private_key["use"],
        "alg": _test_private_key["alg"],
        "n": _test_private_key["n"],
        "e": _test_private_key["e"],
    }


@pytest.fixture
def auth(
    fake_keycloak_url: str,
    fake_realm: str,
    fake_client_id: str,
) -> KeycloakJwtAuth:
    """Create a KeycloakJwtAuth instance for testing with scope."""
    return KeycloakJwtAuth(
        keycloak_url=fake_keycloak_url,
        realm=fake_realm,
        client_id=fake_client_id,
        scope=FakeAuthScopes.READ_ALL,
    )


@pytest.fixture
def auth_with_role(
    fake_keycloak_url: str,
    fake_realm: str,
    fake_client_id: str,
) -> KeycloakJwtAuth:
    """Create a KeycloakJwtAuth instance for testing with role."""
    return KeycloakJwtAuth(
        keycloak_url=fake_keycloak_url,
        realm=fake_realm,
        client_id=fake_client_id,
        role=FakeAuthRoles.READER,
    )


@pytest.fixture
def fake_request() -> Request:
    """Create a fake request for testing."""
    return Request(scope={"type": "http", "path": "/test"})


@pytest.fixture
def generate_keycloak_token(
    fake_keycloak_url: str,
    fake_realm: str,
    fake_client_id: str,
) -> TokenGenerator:
    """Create a function that generates fake Keycloak tokens."""
    private_key = JsonWebKey.import_key(_test_private_key)

    def __generate_token(
        user_payload: dict | None = None,
        scope: str | None = None,
        role: str | None = None,
    ) -> str:
        if user_payload is None:
            user_payload = {}

        now = datetime.datetime.now(datetime.UTC)
        payload = {
            "sub": "test-user-id",
            "iat": int(now.timestamp()),
            "exp": int((now + datetime.timedelta(minutes=10)).timestamp()),
            "aud": fake_client_id,
            "iss": f"{fake_keycloak_url}/realms/{fake_realm}",
            "azp": "destiny-auth-client",
            "typ": "Bearer",
        }

        payload.update(user_payload)

        if scope:
            payload["scope"] = f"openid profile email {scope}"
        if role:
            payload["realm_access"] = {"roles": [role]}

        header = {"alg": "RS256", "kid": _test_private_key["kid"]}
        return authlib_jwt.encode(header, payload, private_key).decode("utf-8")

    return __generate_token


async def test_verify_token_success(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
) -> None:
    """Test that a valid token is successfully verified."""
    payload = {"sub": "test_subject"}
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(payload)
    result = await auth.verify_token(token)
    assert result["sub"] == "test_subject"


async def test_verify_token_cached_jwks(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
):
    """Test that we cache the JWKS fetched from Keycloak."""
    payload = {"sub": "test_subject"}
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(payload)

    result = await auth.verify_token(token)
    assert result["sub"] == "test_subject"

    result = await auth.verify_token(token)
    assert result["sub"] == "test_subject"

    # Check we have one request to Keycloak despite verifying two tokens
    assert len(httpx_mock.get_requests()) == 1


async def test_verify_token_invalid(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
):
    """Test that we raise an appropriate exception with an invalid token."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token("sample.jwt.token")
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Unable to parse authentication token" in excinfo.value.detail


async def test_verify_token_expired(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
):
    """Test that we raise an appropriate exception with an expired token."""
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "exp": int((now - datetime.timedelta(minutes=10)).timestamp()),
    }
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(payload)
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Token is expired."


async def test_verify_token_incorrect_audience(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
):
    """Test that we raise an exception with a token having incorrect audience."""
    payload = {
        "aud": "wrong-client-id",
    }
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(payload)
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid token claims" in excinfo.value.detail


async def test_verify_token_jwks_retry(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
):
    """Test that we get fresh JWKS if the cached one is stale."""
    # Pre-populate cache with stale JWKS
    stale_public_key = fake_public_key.copy()
    stale_public_key["n"] = "stale_n"
    auth.cache["jwks"] = JsonWebKey.import_key_set({"keys": [stale_public_key]})

    # Add fresh JWKS response
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    payload = {"sub": "test_subject"}
    token = generate_keycloak_token(payload)
    result = await auth.verify_token(token)
    assert result["sub"] == "test_subject"

    # Verify we made a request to refresh JWKS
    assert len(httpx_mock.get_requests()) == 1


async def test_verify_token_parse_failure_after_retry(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
):
    """Test that we only retry once if we fail to verify a token."""
    # Pre-populate cache with stale JWKS
    stale_public_key = fake_public_key.copy()
    stale_public_key["n"] = "stale_n"
    auth.cache["jwks"] = JsonWebKey.import_key_set({"keys": [stale_public_key]})

    # Return stale JWKS again on refresh
    httpx_mock.add_response(json={"keys": [stale_public_key]})

    token = generate_keycloak_token()
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)

    assert len(httpx_mock.get_requests()) == 1
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Unable to parse authentication token" in excinfo.value.detail


async def test_requires_scope_success(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
    fake_request: Request,
):
    """Test that we successfully validate a token with the requested scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(scope=FakeAuthScopes.READ_ALL.value)
    credentials = Mock()
    credentials.credentials = token
    assert await auth(fake_request, credentials) is True


async def test_requires_role_success(
    httpx_mock: HTTPXMock,
    auth_with_role: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
    fake_request: Request,
):
    """Test that we successfully validate a token with the requested role."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(role=FakeAuthRoles.READER.value)
    credentials = Mock()
    credentials.credentials = token
    assert await auth_with_role(fake_request, credentials) is True


async def test_requires_scope_not_found(
    httpx_mock: HTTPXMock,
    auth: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
    fake_request: Request,
):
    """Test that we raise an exception with a token without the appropriate scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(scope="wrong.scope")
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth(fake_request, credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert "scope claim does not contain the required scope" in excinfo.value.detail


async def test_requires_role_not_found(
    httpx_mock: HTTPXMock,
    auth_with_role: KeycloakJwtAuth,
    fake_public_key: dict,
    generate_keycloak_token: TokenGenerator,
    fake_request: Request,
):
    """Test that we raise an exception with a token without the appropriate role."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_keycloak_token(role="wrong.role")
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth_with_role(fake_request, credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert "roles claim does not contain the required role" in excinfo.value.detail


async def test_missing_credentials(
    auth: KeycloakJwtAuth,
    fake_request: Request,
):
    """Test that we raise an exception when credentials are missing."""
    with pytest.raises(HTTPException) as excinfo:
        await auth(fake_request, None)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Authorization HTTPBearer header missing."


async def test_custom_issuer_url(
    httpx_mock: HTTPXMock,
    fake_public_key: dict,
    fake_realm: str,
    fake_client_id: str,
):
    """Test that custom issuer URL is used for validation while JWKS uses keycloak_url."""  # noqa: E501
    # Internal URL for JWKS fetching
    keycloak_url = "http://keycloak:8080"
    # External URL for issuer validation
    issuer_url = "http://localhost:8080"

    auth = KeycloakJwtAuth(
        keycloak_url=keycloak_url,
        realm=fake_realm,
        client_id=fake_client_id,
        scope=FakeAuthScopes.READ_ALL,
        issuer_url=issuer_url,
    )

    # JWKS should be fetched from keycloak_url
    httpx_mock.add_response(
        url=f"{keycloak_url}/realms/{fake_realm}/protocol/openid-connect/certs",
        json={"keys": [fake_public_key]},
    )

    # Generate token with issuer_url
    private_key = JsonWebKey.import_key(_test_private_key)
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": "test-user-id",
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(minutes=10)).timestamp()),
        "aud": fake_client_id,
        "iss": f"{issuer_url}/realms/{fake_realm}",  # Using issuer_url
        "scope": f"openid {FakeAuthScopes.READ_ALL.value}",
    }
    header = {"alg": "RS256", "kid": _test_private_key["kid"]}
    token = authlib_jwt.encode(header, payload, private_key).decode("utf-8")

    result = await auth.verify_token(token)
    assert result["sub"] == "test-user-id"
