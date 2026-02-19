"""Keycloak authentication flow for CLI and Python clients using authlib."""

import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from authlib.integrations.httpx_client import OAuth2Client


@dataclass
class TokenResponse:
    """Token response from Keycloak."""

    access_token: str
    refresh_token: str | None
    expires_in: int
    token_type: str
    scope: str


class KeycloakAuthCodeFlow:
    """
    Authorization code flow with PKCE for CLI and Python clients.

    Uses authlib for OAuth2/OIDC handling, which provides built-in support for
    PKCE, token refresh, and error handling.

    Uses the same `destiny-auth-client` as all other human users.
    Scopes are determined by the user's group membership (consumers vs developers).

    Example usage:
        flow = KeycloakAuthCodeFlow(
            keycloak_url="http://localhost:8080",
            realm="destiny",
        )
        token = flow.authenticate(scopes=["reference.reader.all"])
    """

    def __init__(
        self,
        keycloak_url: str,
        realm: str,
        client_id: str = "destiny-auth-client",
        callback_port: int = 8400,
    ) -> None:
        """
        Initialize Keycloak auth flow.

        Args:
            keycloak_url: Base URL of the Keycloak server
            realm: Keycloak realm name
            client_id: OIDC client ID (defaults to destiny-auth-client)
            callback_port: Port for local callback server

        """
        self.keycloak_url = keycloak_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.callback_port = callback_port
        self.redirect_uri = f"http://localhost:{callback_port}/callback"

        base = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect"
        self.authorization_endpoint = f"{base}/auth"
        self.token_endpoint = f"{base}/token"

    def _create_client(self) -> OAuth2Client:
        """Create an OAuth2Client configured for PKCE."""
        return OAuth2Client(
            client_id=self.client_id,
            token_endpoint_auth_method="none",  # Public client  # noqa: S106
            code_challenge_method="S256",
        )

    def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an access token using a refresh token.

        Args:
            refresh_token: The refresh token to use

        Returns:
            TokenResponse with new access and refresh tokens

        """
        client = self._create_client()
        token = client.refresh_token(
            self.token_endpoint,
            refresh_token=refresh_token,
        )

        return TokenResponse(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            expires_in=token["expires_in"],
            token_type=token["token_type"],
            scope=token.get("scope", ""),
        )

    def authenticate(
        self,
        scopes: list[str] | None = None,
        *,
        open_browser: bool = True,
    ) -> TokenResponse:
        """
        Perform the full authentication flow.

        Opens a browser for the user to log in, then exchanges
        the authorization code for tokens.

        Args:
            scopes: Optional list of scopes to request
            open_browser: Whether to automatically open the browser

        Returns:
            TokenResponse with access and refresh tokens

        """
        client = self._create_client()

        # Build scope string
        scope_str = "openid profile email"
        if scopes:
            scope_str = f"{scope_str} {' '.join(scopes)}"

        # Generate authorization URL with PKCE
        auth_url, _state = client.create_authorization_url(
            self.authorization_endpoint,
            redirect_uri=self.redirect_uri,
            scope=scope_str,
        )

        # Store the received authorization response
        received_response: dict[str, Any] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/callback":
                    # Store the full callback URL for authlib to parse
                    received_response["url"] = (
                        f"http://localhost:{self.server.server_port}{self.path}"  # type: ignore[attr-defined]
                    )
                    params = parse_qs(parsed.query)

                    if "error" in params:
                        received_response["error"] = params["error"][0]
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(f"Error: {params['error'][0]}".encode())
                    else:
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(
                            b"<html><body><h1>Authentication successful!</h1>"
                            b"<p>You can close this window.</p></body></html>"
                        )

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
                pass  # Suppress logging

        server = HTTPServer(("localhost", self.callback_port), CallbackHandler)
        server.timeout = 300  # 5 minute timeout

        if open_browser:
            webbrowser.open(auth_url)
        else:
            print(f"Please open this URL in your browser:\n{auth_url}")  # noqa: T201

        # Wait for callback
        while "url" not in received_response and "error" not in received_response:
            server.handle_request()

        server.server_close()

        if "error" in received_response:
            msg = f"Authentication failed: {received_response['error']}"
            raise RuntimeError(msg)

        # Exchange authorization code for tokens using authlib
        # authlib handles PKCE verification automatically
        token = client.fetch_token(
            self.token_endpoint,
            authorization_response=received_response["url"],
            redirect_uri=self.redirect_uri,
        )

        return TokenResponse(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            expires_in=token["expires_in"],
            token_type=token["token_type"],
            scope=token.get("scope", ""),
        )
