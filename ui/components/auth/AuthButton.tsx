// AuthButton component for login/logout

import { useMsal } from "@azure/msal-react";
import { loginRequest } from "../../lib/msalConfig";

export default function AuthButton() {
  const { instance, accounts } = useMsal();

  const handleLogin = () => {
    instance.loginRedirect(loginRequest);
  };

  const handleLogout = () => {
    instance.logoutRedirect();
  };

  return accounts.length ? (
    <button
      className="auth-btn"
      onClick={handleLogout}
      style={{
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
      }}
    >
      Sign out
    </button>
  ) : (
    <button
      className="auth-btn"
      onClick={handleLogin}
      style={{
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
      }}
    >
      Sign in with Azure
    </button>
  );
}
