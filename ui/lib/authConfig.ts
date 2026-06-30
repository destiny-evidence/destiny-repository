/**
 * Unified authentication configuration supporting both Azure AD (MSAL) and Keycloak (OIDC).
 *
 * The auth provider is determined by the AUTH_PROVIDER runtime config value.
 */

import { Configuration } from "@azure/msal-browser";
import { AuthProviderProps } from "react-oidc-context";
import { WebStorageStateStore } from "oidc-client-ts";

import { getRuntimeConfig } from "./runtimeConfig";

export type AuthProvider = "azure" | "keycloak" | "local";

/**
 * Get the current auth provider from runtime config.
 */
export async function getAuthProvider(): Promise<AuthProvider> {
  const runtime = await getRuntimeConfig();
  const env = runtime.ENV || process.env.ENV;

  // In local environment, auth is bypassed
  if (env === "local") {
    return "local";
  }

  const provider =
    runtime.AUTH_PROVIDER || process.env.AUTH_PROVIDER || "azure";
  return provider as AuthProvider;
}

/**
 * Create MSAL configuration for Azure AD.
 */
export async function createMsalConfig(): Promise<Configuration> {
  const runtime = await getRuntimeConfig();
  const redirectUri =
    typeof window !== "undefined"
      ? `${window.location.protocol}//${window.location.host}/`
      : process.env.NEXT_PUBLIC_AZURE_REDIRECT_URI || "";

  return {
    auth: {
      clientId:
        runtime.NEXT_PUBLIC_AZURE_CLIENT_ID ||
        process.env.NEXT_PUBLIC_AZURE_CLIENT_ID ||
        "",
      authority:
        runtime.NEXT_PUBLIC_AZURE_LOGIN_URL ||
        process.env.NEXT_PUBLIC_AZURE_LOGIN_URL ||
        "",
      redirectUri,
    },
    cache: {
      cacheLocation: "localStorage",
      storeAuthStateInCookie: false,
    },
  };
}

/**
 * Get MSAL login request scopes.
 */
export async function getMsalLoginRequest(): Promise<{ scopes: string[] }> {
  const runtime = await getRuntimeConfig();
  return {
    scopes: [
      "openid",
      "profile",
      `api://${
        runtime.NEXT_PUBLIC_AZURE_APPLICATION_ID ||
        process.env.NEXT_PUBLIC_AZURE_APPLICATION_ID
      }/reference.reader.all`,
    ],
  };
}

/**
 * Create OIDC configuration for Keycloak.
 */
export async function createKeycloakConfig(): Promise<AuthProviderProps> {
  const runtime = await getRuntimeConfig();
  const redirectUri =
    typeof window !== "undefined"
      ? `${window.location.protocol}//${window.location.host}/`
      : "";

  const keycloakUrl =
    runtime.KEYCLOAK_URL || process.env.KEYCLOAK_URL || "http://localhost:8080";
  const realm =
    runtime.KEYCLOAK_REALM || process.env.KEYCLOAK_REALM || "destiny";
  const clientId =
    runtime.KEYCLOAK_CLIENT_ID ||
    process.env.KEYCLOAK_CLIENT_ID ||
    "destiny-auth-client";

  return {
    authority: `${keycloakUrl}/realms/${realm}`,
    client_id: clientId,
    redirect_uri: redirectUri,
    post_logout_redirect_uri: redirectUri,
    scope: "openid profile email",
    userStore:
      typeof window !== "undefined"
        ? new WebStorageStateStore({ store: window.localStorage })
        : undefined,
    // Disable automatic silent renew and session monitoring to avoid cross-origin iframes.
    // Keycloak is on a different domain, so the IdP session cookie is blocked as third-party.
    // Token refresh is handled manually in KeycloakAuthBridge's getToken() via refresh tokens.
    automaticSilentRenew: false,
    monitorSession: false,
    revokeTokensOnSignout: true,
    onSigninCallback: () => {
      // Remove OIDC query params from URL after sign-in
      window.history.replaceState({}, document.title, window.location.pathname);
    },
  };
}
