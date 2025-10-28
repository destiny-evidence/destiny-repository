"use client";

import "../app/globals.css";
import { MsalProvider } from "@azure/msal-react";
import { PublicClientApplication } from "@azure/msal-browser";
import { msalConfig } from "../lib/msalConfig";

const msalInstance = new PublicClientApplication(msalConfig);

import { useEffect, useState } from "react";
import AuthButton from "../components/auth/AuthButton";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    msalInstance
      .initialize()
      .then(() => setInitialized(true))
      .catch(() => setInitialized(true)); // Render anyway on error
  }, []);

  return (
    <html lang="en">
      <body>
        <MsalProvider instance={msalInstance}>
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
