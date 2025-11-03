"use client";

import "../app/globals.css";
import { MsalProvider } from "@azure/msal-react";
import { PublicClientApplication } from "@azure/msal-browser";
import { createMsalConfig } from "../lib/msalConfig";
import { useEffect, useState } from "react";
import AuthButton from "../components/auth/AuthButton";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [msalInstance, setMsalInstance] =
    useState<PublicClientApplication | null>(null);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    async function setupMsal() {
      const config = await createMsalConfig();
      const instance = new PublicClientApplication(config);
      await instance.initialize();
      setMsalInstance(instance);
      setInitialized(true);
    }
    setupMsal();
  }, []);

  return (
    <html lang="en">
      <body>
        <MsalProvider
          instance={
            msalInstance ??
            new PublicClientApplication({ auth: { clientId: "" } })
          }
        >
          <nav className="navbar">
            <span className="navbar-title">DESTINY Repository</span>
            <div className="navbar-actions">
              <a className="navbar-link active" href="/references">
                Reference Lookup
              </a>
              <div id="auth-btn-container" style={{ marginLeft: 24 }}>
                <AuthButton />
              </div>
            </div>
          </nav>
          <div className="main-content">{initialized ? children : null}</div>
        </MsalProvider>
      </body>
    </html>
  );
}
