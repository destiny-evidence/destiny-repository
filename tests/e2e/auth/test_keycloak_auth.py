"""End-to-end tests for Keycloak authentication."""

import httpx


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

    async def test_token_with_wrong_scope_fails(
        self,
        keycloak_api_client: httpx.AsyncClient,
        keycloak_url: str,
    ):
        """Test that a token without required scope fails authorization."""
        # Get a token with only openid scope (no reference.reader.all)
        token_url = f"{keycloak_url}/realms/destiny/protocol/openid-connect/token"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": "destiny-auth-client",
                    "username": "testuser",
                    "password": "testpass",
                    "scope": "openid",  # Missing reference.reader.all
                },
            )
            response.raise_for_status()
            minimal_token = response.json()["access_token"]

        # Try to access references endpoint
        response = await keycloak_api_client.get(
            "references/search/?q=test",
            headers={"Authorization": f"Bearer {minimal_token}"},
        )
        # Should fail with 403 Forbidden (token is valid but lacks scope)
        assert response.status_code == 403

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

    async def test_robots_endpoint_with_admin_scope(
        self,
        keycloak_api_client: httpx.AsyncClient,
        keycloak_token_all_scopes: str,
    ):
        """Test that admin endpoints work with appropriate scope."""
        # Create a robot (requires robot.writer.all scope)
        response = await keycloak_api_client.post(
            "robots/",
            headers={"Authorization": f"Bearer {keycloak_token_all_scopes}"},
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

    async def test_healthcheck_no_auth_required(
        self,
        keycloak_api_client: httpx.AsyncClient,
    ):
        """Test that healthcheck endpoint works without auth."""
        response = await keycloak_api_client.get(
            "system/healthcheck/?azure_blob_storage=false"
        )
        assert response.status_code == 200
