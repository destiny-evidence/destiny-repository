"""End-to-end tests for Keycloak authentication."""

import base64
import json

import httpx


def _claims(token: str) -> dict:
    """Decode a JWT payload without verifying it."""
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


class TestKeycloakAuth:
    """Test Keycloak authentication with the API."""

    async def test_unauthenticated_request_fails(
        self,
        keycloak_api_client: httpx.AsyncClient,
    ):
        """Test that unauthenticated requests to protected endpoints fail."""
        # Use search endpoint with required params
        response = await keycloak_api_client.get("references/search/?q=test")
        assert response.status_code == 401

    async def test_authenticated_request_succeeds(
        self,
        keycloak_api_client: httpx.AsyncClient,
        keycloak_token: str,
    ):
        """Test that authenticated requests with Keycloak token succeed."""
        response = await keycloak_api_client.get(
            "references/search/?q=test",
            headers={"Authorization": f"Bearer {keycloak_token}"},
        )
        # 200 for success (search returns empty list)
        assert response.status_code == 200

    async def test_expired_token_fails(
        self,
        keycloak_api_client: httpx.AsyncClient,
    ):
        """Test that an expired/invalid token fails."""
        # Use an obviously invalid token
        response = await keycloak_api_client.get(
            "references/search/?q=test",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401

    async def test_client_role_grants_access(
        self,
        keycloak_api_client: httpx.AsyncClient,
        keycloak_token: str,
    ):
        """
        Test that a client role held on the repository's client grants access.

        testuser holds robot.writer on destiny-repository-client-test via the
        developers-test group.
        """
        response = await keycloak_api_client.post(
            "robots/",
            headers={"Authorization": f"Bearer {keycloak_token}"},
            json={
                "name": "Test Robot",
                "description": "A robot created during e2e test",
                "owner": "test@example.com",
            },
        )
        # 201 Created
        assert response.status_code == 201
        robot_data = response.json()
        assert robot_data["name"] == "Test Robot"
        assert "id" in robot_data
        assert "client_secret" in robot_data

    async def test_unheld_client_role_is_denied(
        self,
        keycloak_api_client: httpx.AsyncClient,
        keycloak_restricted_token: str,
    ):
        """
        Test that a role the principal does not hold denies access.

        restricteduser holds reference.reader alone via consumers-test.
        """
        response = await keycloak_api_client.post(
            "robots/",
            headers={"Authorization": f"Bearer {keycloak_restricted_token}"},
            json={
                "name": "Unauthorized Robot",
                "description": "Should not be created",
                "owner": "restricted@example.com",
            },
        )
        assert response.status_code == 403

    async def test_realm_role_confers_no_access(
        self,
        keycloak_api_client: httpx.AsyncClient,
        keycloak_legacy_realm_role_token: str,
    ):
        """
        Test that a realm role of the same name confers nothing.

        legacyuser holds robot.writer as a realm role only. Realm roles are
        realm-global and so cannot express an environment-scoped grant.
        """
        # Assert the role is in the token, so this tests that the API ignores
        # realm_access rather than that Keycloak withheld the role.
        claims = _claims(keycloak_legacy_realm_role_token)
        assert "robot.writer" in claims["realm_access"]["roles"]
        assert "robot.writer" not in claims.get("resource_access", {}).get(
            "destiny-repository-client-test", {}
        ).get("roles", [])

        response = await keycloak_api_client.post(
            "robots/",
            headers={"Authorization": f"Bearer {keycloak_legacy_realm_role_token}"},
            json={
                "name": "Realm Role Robot",
                "description": "Should not be created",
                "owner": "legacy@example.com",
            },
        )
        assert response.status_code == 403

    async def test_healthcheck_no_auth_required(
        self,
        keycloak_api_client: httpx.AsyncClient,
    ):
        """Test that healthcheck endpoint works without auth."""
        response = await keycloak_api_client.get(
            "system/healthcheck/?azure_blob_storage=false"
        )
        assert response.status_code == 200
