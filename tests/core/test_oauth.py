"""Test auth tools."""

import datetime
from collections.abc import Callable
from enum import StrEnum
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from joserfc.jwk import KeySet, RSAKey
from pytest_httpx import HTTPXMock

from app.api.auth import AuthMethod, AzureJwtAuth, StrategyAuth, SuccessAuth


class FakeAuthScopes(StrEnum):
    """Fake authentication scoes used for testing authentication."""

    READ_ALL = "read.all"


def _stale_jwks(fake_public_key: dict) -> KeySet:
    """Build a JWKS whose key shares the fake key's kid but not its material."""
    stale_key = RSAKey.generate_key(
        2048, parameters={"kid": fake_public_key["kid"], "use": "sig", "alg": "RS256"}
    )
    return KeySet([RSAKey.import_key(stale_key.as_dict(private=False))])


@pytest.fixture
def auth(
    fake_application_id: str,
) -> AzureJwtAuth:
    """Create fixure AzureJwtAuth instance for testing."""
    return AzureJwtAuth(fake_application_id, scope=FakeAuthScopes.READ_ALL)


@pytest.fixture
def auth_with_role(
    fake_application_id: str,
) -> AzureJwtAuth:
    """Create fixure AzureJwtAuth instance for testing."""
    return AzureJwtAuth(fake_application_id, role=FakeAuthScopes.READ_ALL)


@pytest.fixture
def fake_request() -> Request:
    """Create a fake request for testing."""
    return Request(scope={"type": "http", "path": "/test"})


async def test_verify_token_success(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
) -> None:
    """Test that a valid token is successfully verified."""
    payload = {"sub": "test_subject"}
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(payload)
    result = await auth.verify_token(token)
    assert payload["sub"] == result["sub"]


async def test_verify_token_cached_jwks(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
):
    """Test that we cache the jwks fetched from Azure."""
    payload = {"sub": "test_subject"}
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(payload)

    result = await auth.verify_token(token)
    assert payload["sub"] == result["sub"]

    result = await auth.verify_token(token)
    assert payload["sub"] == result["sub"]

    # Check we have one request to Azure despite verifying two tokens
    assert len(httpx_mock.get_requests()) == 1


async def test_verify_token_invalid(
    httpx_mock: HTTPXMock, auth: AzureJwtAuth, fake_public_key: dict
):
    """Test that we raise an appropriate exception with an invalid token."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token("sample.jwt.token")
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Unable to parse authentication token."


async def test_verify_token_expired(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
):
    """Test that we raise an appropriate exception with an expired token."""
    payload = {
        "exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=10),
    }
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(payload)
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Token is expired."


async def test_verify_token_incorrect_claims(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
):
    """Test that we raise an exception with a token including incorrect claims."""
    payload = {
        "aud": "api://wrong_application_id",
    }
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(payload)
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Incorrect claims" in excinfo.value.detail
    assert "aud=" in excinfo.value.detail


async def test_verify_token_issued_in_future(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
):
    """Test that the claim error names the failing claim, not just aud/iss."""
    payload = {
        "iat": datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    }
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(payload)
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "issued in the future" in excinfo.value.detail


async def test_verify_token_skips_unparseable_jwks_entries(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
):
    """Test that a bad key in the JWKS doesn't block verification with a good one."""
    bad_keys = [
        {"kid": "no-kty"},
        {"kty": "RSA", "kid": "bad-n", "n": "not base64", "e": "AQAB"},
        {"kty": "EC", "kid": "bad-crv", "crv": "P-999", "x": "a", "y": "b"},
    ]
    httpx_mock.add_response(json={"keys": [*bad_keys, fake_public_key]})

    payload = {"sub": "test_subject"}
    token = generate_fake_token(payload)
    result = await auth.verify_token(token)
    assert payload["sub"] == result["sub"]


async def test_verify_token_no_keys(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[], str],
):
    """Test that we raise an exception when our token's kid can't be found."""
    httpx_mock.add_response(json={"keys": [{**fake_public_key, "kid": "wrong_kid"}]})

    token = generate_fake_token()
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Unable to find appropriate key."


async def test_verify_token_jwks_retry(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[dict], str],
):
    """Test that we get a fresh public key if the one we have is stale."""
    auth.cache["jwks"] = _stale_jwks(fake_public_key)
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    payload = {"sub": "test_subject"}
    token = generate_fake_token(payload)
    result = await auth.verify_token(token)
    assert payload["sub"] == result["sub"]

    assert len(httpx_mock.get_requests()) == 1
    assert auth.cache["jwks"].as_dict() == {"keys": [fake_public_key]}


async def test_verify_token_parse_failure_after_retry(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[], str],
):
    """Test that we only retry once if we fail to find a key for our token."""
    stale_jwks = _stale_jwks(fake_public_key)
    auth.cache["jwks"] = stale_jwks
    httpx_mock.add_response(json=stale_jwks.as_dict())

    token = generate_fake_token()
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)

    assert len(httpx_mock.get_requests()) == 1
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Unable to parse authentication token."


async def test_requires_read_all_scope_success(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
    fake_request: Request,
):
    """Test that we successfully validate a token with the requested scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(scope=FakeAuthScopes.READ_ALL.value)
    credentials = Mock()
    credentials.credentials = token
    assert isinstance(await auth(fake_request, credentials), frozenset)


async def test_requires_read_all_role_success(
    httpx_mock: HTTPXMock,
    auth_with_role: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
    fake_request: Request,
):
    """Test that we successfully validate a token with the requested scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(role=FakeAuthScopes.READ_ALL.value)
    credentials = Mock()
    credentials.credentials = token
    assert isinstance(await auth_with_role(fake_request, credentials), frozenset)


async def test_requires_read_all_scope_not_found(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
    fake_request: Request,
):
    """Test that we raise an exception with a token without the appropriate scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(scope="not.read.all")
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth(fake_request, credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert (
        excinfo.value.detail
        == "IDW10203: The scope permissions (scp) claim does not contain the required scope read.all"  # noqa: E501
    )


async def test_requires_read_all_role_not_found(
    httpx_mock: HTTPXMock,
    auth_with_role: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
    fake_request: Request,
):
    """Test that we raise an exception with a token without the appropriate scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(role="not.read.all")
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth_with_role(fake_request, credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert (
        excinfo.value.detail
        == "IDW10203: The role permissions (roles) claim does not contain the required role read.all"  # noqa: E501
    )


async def test_required_scope_and_role_not_present(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
    fake_request: Request,
):
    """Test that we raise an exception when no scope is present."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token()
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth(fake_request, credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert (
        excinfo.value.detail
        == "IDW10201: Neither scope or roles claim was found in the bearer token."
    )


async def test_strategy_auth_selection(fake_request: Request):
    """Test that we can use a strategy."""
    mock_auth_method = AsyncMock(AuthMethod)
    strategy_auth = StrategyAuth(selector=lambda: mock_auth_method)

    await strategy_auth(
        fake_request, HTTPAuthorizationCredentials(scheme="Bearer", credentials="foo")
    )
    assert mock_auth_method.called


async def test_fake_auth_success(
    generate_fake_token: Callable[..., str], fake_request: Request
):
    """Test that our fake auth method succeeds on demand, with and without tokens."""
    auth = SuccessAuth()
    creds = Mock(credentials=generate_fake_token())

    assert isinstance(await auth(fake_request, creds), frozenset)
    assert isinstance(await auth(fake_request, None), frozenset)
