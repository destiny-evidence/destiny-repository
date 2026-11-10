// AuthButton component for login/logout

import { useAuth } from "@/auth/AuthContext";

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

export default function AuthButton() {
  const { enabled, authenticated, username, login, logout } = useAuth();

  if (!enabled) {
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

  return authenticated ? (
    <button class="auth-btn" onClick={logout} style={buttonStyle}>
      Sign out{username ? ` (${username})` : ""}
    </button>
  ) : (
    <button class="auth-btn" onClick={login} style={buttonStyle}>
      Sign in
    </button>
  );
}
