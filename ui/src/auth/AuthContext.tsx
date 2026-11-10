import { createContext, type ComponentChildren } from "preact";
import { useContext, useEffect, useState } from "preact/hooks";
import { authEnabled, keycloak, login, logout } from "./keycloak";

interface AuthState {
  /** False when the build runs with auth disabled (local development). */
  enabled: boolean;
  /** Always true when auth is disabled: the API accepts anonymous calls. */
  authenticated: boolean;
  username: string | undefined;
  login: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

interface ProfileClaims {
  name?: string;
  preferred_username?: string;
  email?: string;
}

function readUsername(): string | undefined {
  const profile = (keycloak?.tokenParsed as ProfileClaims | undefined) ?? {};
  return profile.name ?? profile.preferred_username ?? profile.email;
}

export function AuthProvider({ children }: { children: ComponentChildren }) {
  const [, setVersion] = useState(0);

  useEffect(() => {
    if (!keycloak) return;
    const kc = keycloak;
    // Force consumers to re-read keycloak state when it changes.
    const bump = () => setVersion((v) => v + 1);
    kc.onAuthSuccess = bump;
    kc.onAuthRefreshSuccess = bump;
    kc.onAuthLogout = bump;
    return () => {
      kc.onAuthSuccess = undefined;
      kc.onAuthRefreshSuccess = undefined;
      kc.onAuthLogout = undefined;
    };
  }, []);

  const value: AuthState = {
    enabled: authEnabled,
    authenticated: authEnabled ? !!keycloak?.authenticated : true,
    username: readUsername(),
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
