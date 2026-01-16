"use client";

import "../app/globals.css";
import { MsalProvider } from "@azure/msal-react";
import { PublicClientApplication } from "@azure/msal-browser";
import { AuthProvider as OidcAuthProvider } from "react-oidc-context";
import { AuthProviderProps } from "react-oidc-context";
import { useEffect, useState } from "react";
import AuthButton from "../components/auth/AuthButton";
import {
  AuthProvider,
  getAuthProvider,
  createMsalConfig,
  createKeycloakConfig,
} from "../lib/authConfig";
import { AuthProviderContext } from "../lib/api/useApi";

interface AuthState {
  provider: AuthProvider;
  msalInstance: PublicClientApplication | null;
  oidcConfig: AuthProviderProps | null;
  initialized: boolean;
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

  const renderContent = () => (
    <AuthProviderContext.Provider value={authState.provider}>
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
    </AuthProviderContext.Provider>
  );

  // Render based on auth provider
  if (authState.provider === "azure" && authState.msalInstance) {
    return (
      <html lang="en">
        <body>
          <MsalProvider instance={authState.msalInstance}>
            {renderContent()}
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
            {renderContent()}
          </OidcAuthProvider>
        </body>
      </html>
    );
  }

  // Local or initializing - render without auth provider
  return (
    <html lang="en">
      <body>{renderContent()}</body>
    </html>
  );
}
