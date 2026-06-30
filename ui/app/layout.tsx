"use client";

import "../app/globals.css";
import { MsalProvider, useMsal } from "@azure/msal-react";
import {
  PublicClientApplication,
  InteractionStatus,
} from "@azure/msal-browser";
import {
  AuthProvider as OidcAuthProvider,
  AuthProviderProps,
  useAuth,
} from "react-oidc-context";
import { useEffect, useState } from "react";
import AuthButton from "../components/auth/AuthButton";
import {
  AuthProvider,
  getAuthProvider,
  createMsalConfig,
  createKeycloakConfig,
  getMsalLoginRequest,
} from "../lib/authConfig";
import { AuthContext } from "../lib/api/useApi";

interface AuthState {
  provider: AuthProvider;
  msalInstance: PublicClientApplication | null;
  oidcConfig: AuthProviderProps | null;
  initialized: boolean;
}

/**
 * Provides AuthContext for Azure AD. Must be rendered inside MsalProvider.
 */
function AzureAuthBridge({ children }: { children: React.ReactNode }) {
  const { instance, accounts, inProgress } = useMsal();

  const isLoggedIn = (accounts?.length ?? 0) > 0;
  const isLoginProcessing =
    inProgress === InteractionStatus.Login ||
    inProgress === InteractionStatus.AcquireToken ||
    inProgress === InteractionStatus.HandleRedirect ||
    inProgress === InteractionStatus.SsoSilent;

  async function getToken(): Promise<string | undefined> {
    if (!accounts || accounts.length === 0) return undefined;

    try {
      const request = await getMsalLoginRequest();
      const resp = await instance.acquireTokenSilent({
        ...request,
        account: accounts[0],
      });
      return resp?.accessToken;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.warn("acquireTokenSilent failed, starting redirect:", message);
      try {
        const request = await getMsalLoginRequest();
        instance.acquireTokenRedirect({
          ...request,
          account: accounts[0],
        });
      } catch (redirectErr) {
        console.error("acquireTokenRedirect failed:", redirectErr);
      }
      return undefined;
    }
  }

  return (
    <AuthContext.Provider
      value={{ getToken, isLoggedIn, isLoginProcessing, provider: "azure" }}
    >
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Provides AuthContext for Keycloak OIDC. Must be rendered inside OidcAuthProvider.
 */
function KeycloakAuthBridge({ children }: { children: React.ReactNode }) {
  const auth = useAuth();

  const isLoggedIn = auth.isAuthenticated;
  const isLoginProcessing = auth.isLoading;

  async function getToken(): Promise<string | undefined> {
    if (!auth.isAuthenticated || !auth.user) return undefined;

    // Refresh the token if it expires within 30 seconds.
    if (auth.user.expired || (auth.user.expires_in ?? 0) < 30) {
      // Without a refresh token, signinSilent() falls back to an iframe that needs the IdP session cookie.
      // While Keycloak is in a different domain, browsers will block this as a third-party cookie.
      // So we bail out instead for now.
      if (!auth.user.refresh_token) {
        return undefined;
      }
      try {
        const renewed = await auth.signinSilent();
        return renewed?.access_token;
      } catch {
        return undefined;
      }
    }

    return auth.user.access_token;
  }

  return (
    <AuthContext.Provider
      value={{ getToken, isLoggedIn, isLoginProcessing, provider: "keycloak" }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [authState, setAuthState] = useState<AuthState>({
    provider: "local",
    msalInstance: null,
    oidcConfig: null,
    initialized: false,
  });

  useEffect(() => {
    async function setupAuth() {
      const provider = await getAuthProvider();

      if (provider === "azure") {
        const config = await createMsalConfig();
        const instance = new PublicClientApplication(config);
        await instance.initialize();
        setAuthState({
          provider,
          msalInstance: instance,
          oidcConfig: null,
          initialized: true,
        });
      } else if (provider === "keycloak") {
        const oidcConfig = await createKeycloakConfig();
        setAuthState({
          provider,
          msalInstance: null,
          oidcConfig,
          initialized: true,
        });
      } else {
        // Local environment - no auth needed
        setAuthState({
          provider: "local",
          msalInstance: null,
          oidcConfig: null,
          initialized: true,
        });
      }
    }
    setupAuth();
  }, []);

  const content = (
    <>
      <nav className="navbar">
        <span className="navbar-title">DESTINY Repository</span>
        <div className="navbar-actions">
          <a className="navbar-link active" href="/references">
            References
          </a>
          <div id="auth-btn-container" style={{ marginLeft: 24 }}>
            <AuthButton provider={authState.provider} />
          </div>
        </div>
      </nav>
      <div className="main-content">
        {authState.initialized ? children : null}
      </div>
    </>
  );

  // Render based on auth provider — each inner component calls its own
  // auth hooks safely within the correct provider tree.
  if (authState.provider === "azure" && authState.msalInstance) {
    return (
      <html lang="en">
        <body>
          <MsalProvider instance={authState.msalInstance}>
            <AzureAuthBridge>{content}</AzureAuthBridge>
          </MsalProvider>
        </body>
      </html>
    );
  }

  if (authState.provider === "keycloak" && authState.oidcConfig) {
    return (
      <html lang="en">
        <body>
          <OidcAuthProvider {...authState.oidcConfig}>
            <KeycloakAuthBridge>{content}</KeycloakAuthBridge>
          </OidcAuthProvider>
        </body>
      </html>
    );
  }

  // Local or initializing — default AuthContext provides local defaults
  return (
    <html lang="en">
      <body>{content}</body>
    </html>
  );
}
