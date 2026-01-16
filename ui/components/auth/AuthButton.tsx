// AuthButton component for login/logout - supports both Azure AD and Keycloak

"use client";

import { useMsal } from "@azure/msal-react";
import { useAuth } from "react-oidc-context";
import { getMsalLoginRequest, AuthProvider } from "../../lib/authConfig";

interface AuthButtonProps {
  provider: AuthProvider;
}

const buttonStyle = {
  background: "var(--primary-light)",
  color: "#fff",
  fontWeight: 600,
  border: "none",
  borderRadius: "var(--border-radius)",
  padding: "8px 20px",
  fontSize: "1rem",
  boxShadow: "var(--shadow)",
  marginLeft: 8,
  transition: "background var(--transition), color var(--transition)",
} as const;

function AzureAuthButton() {
  const { instance, accounts } = useMsal();

  const handleLogin = async () => {
    const request = await getMsalLoginRequest();
    await instance.loginRedirect(request);
  };

  const handleLogout = async () => {
    await instance.logoutRedirect();
  };

  return accounts.length ? (
    <button className="auth-btn" onClick={handleLogout} style={buttonStyle}>
      Sign out
    </button>
  ) : (
    <button className="auth-btn" onClick={handleLogin} style={buttonStyle}>
      Sign in
    </button>
  );
}

function KeycloakAuthButton() {
  const auth = useAuth();

  const handleLogin = () => {
    auth.signinRedirect();
  };

  const handleLogout = () => {
    auth.signoutRedirect();
  };

  if (auth.isLoading) {
    return (
      <span
        style={{ ...buttonStyle, background: "transparent", color: "#666" }}
      >
        Loading...
      </span>
    );
  }

  return auth.isAuthenticated ? (
    <button className="auth-btn" onClick={handleLogout} style={buttonStyle}>
      Sign out ({auth.user?.profile.name || auth.user?.profile.email})
    </button>
  ) : (
    <button className="auth-btn" onClick={handleLogin} style={buttonStyle}>
      Sign in
    </button>
  );
}

function LocalAuthButton() {
  return (
    <span
      style={{
        ...buttonStyle,
        background: "var(--secondary-light)",
        cursor: "default",
      }}
    >
      Local Mode
    </span>
  );
}

export default function AuthButton({ provider }: AuthButtonProps) {
  switch (provider) {
    case "azure":
      return <AzureAuthButton />;
    case "keycloak":
      return <KeycloakAuthButton />;
    case "local":
    default:
      return <LocalAuthButton />;
  }
}
