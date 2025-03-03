"""Test auth tools."""

import datetime
from collections.abc import Callable
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, status
from pytest_httpx import HTTPXMock

from app.core.auth import AuthScopes, AzureJwtAuth, FakeAuth


@pytest.fixture
def auth(fake_tenant_id: str, fake_application_id: str) -> AzureJwtAuth:
    """Create fixure AzureJwtAuth instance for testing."""
    return AzureJwtAuth(fake_tenant_id, fake_application_id, AuthScopes.READ_ALL)


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
    assert (
        excinfo.value.detail
        == "Incorrect claims, please check the audience and issuer."
    )


async def test_verify_token_no_keys(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    generate_fake_token: Callable[[], str],
):
    """Test that we raise an exception when our token's kid can't be found."""
    httpx_mock.add_response(json={"keys": [{"kid": "wrong_kid"}]})

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
    stale_public_key = fake_public_key.copy()
    stale_public_key["n"] = "stale_n"
    auth.cache["jwks"] = {"keys": [stale_public_key]}
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    payload = {"sub": "test_subject"}
    token = generate_fake_token(payload)
    result = await auth.verify_token(token)
    assert payload["sub"] == result["sub"]

    assert len(httpx_mock.get_requests()) == 1
    assert auth.cache["jwks"] == {"keys": [fake_public_key]}


async def test_verify_token_parse_failure_after_retry(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[[], str],
):
    """Test that we only retry once if we fail to find a key for our token."""
    stale_public_key = fake_public_key.copy()
    stale_public_key["n"] = "stale_n"
    auth.cache["jwks"] = {"keys": [stale_public_key]}
    httpx_mock.add_response(json={"keys": [stale_public_key]})

    token = generate_fake_token()
    with pytest.raises(HTTPException) as excinfo:
        await auth.verify_token(token)

    assert len(httpx_mock.get_requests()) == 1
    assert excinfo.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert excinfo.value.detail == "Unable to parse authentication token."


async def test_requires_read_all_success(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
):
    """Test that we successfully validate a token with the requested scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(scope=AuthScopes.READ_ALL.value)
    credentials = Mock()
    credentials.credentials = token
    assert await auth(credentials) is True


async def test_requires_read_all_scope_not_found(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
):
    """Test that we raise an exception with a token without the appropriate scope."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token(scope="not.read.all")
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth(credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert (
        excinfo.value.detail
        == "IDW10203: The app permissions (role) claim does not contain the scope read.all"  # noqa: E501
    )


async def test_requires_read_all_scope_not_present(
    httpx_mock: HTTPXMock,
    auth: AzureJwtAuth,
    fake_public_key: dict,
    generate_fake_token: Callable[..., str],
):
    """Test that we raise an exception when no scope is present."""
    httpx_mock.add_response(json={"keys": [fake_public_key]})

    token = generate_fake_token()
    credentials = Mock()
    credentials.credentials = token
    with pytest.raises(HTTPException) as excinfo:
        await auth(credentials)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert (
        excinfo.value.detail
        == "IDW10201: No app permissions (role) claim was found in the bearer token"
    )


async def test_fake_auth_success(generate_fake_token: Callable[..., str]):
    """Test that our fake auth method succeeds on demand."""
    auth = FakeAuth(always_succeed=True)
    creds = Mock(credentials=generate_fake_token())

    assert await auth(creds)


async def test_fake_auth_failure(generate_fake_token: Callable[..., str]):
    """Test that our fake auth fails on demand."""
    auth = FakeAuth(always_succeed=False)
    creds = Mock(credentials=generate_fake_token())

    with pytest.raises(HTTPException) as excinfo:
        await auth(creds)
    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN
    assert excinfo.value.detail == "FakeAuth will never permit this request."
