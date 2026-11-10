import Keycloak from "keycloak-js";
import {
  AUTH_DISABLED,
  KEYCLOAK_CLIENT_ID,
  KEYCLOAK_REALM,
  KEYCLOAK_URL,
} from "@/config";

function requireEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export const authEnabled = !AUTH_DISABLED;

export const keycloak: Keycloak | null = authEnabled
  ? new Keycloak({
      url: requireEnv("VITE_KEYCLOAK_URL", KEYCLOAK_URL),
      realm: requireEnv("VITE_KEYCLOAK_REALM", KEYCLOAK_REALM),
      clientId: requireEnv("VITE_KEYCLOAK_CLIENT_ID", KEYCLOAK_CLIENT_ID),
    })
  : null;

// A failed refresh means the session is gone. Dropping the token flips the UI
// back to signed-out rather than redirecting away from whatever was typed.
function refreshOrSignOut(kc: Keycloak): Promise<boolean> {
  return kc.updateToken(30).then(
    () => true,
    () => {
      kc.clearToken();
      return false;
    },
  );
}

if (keycloak) {
  const kc = keycloak;
  kc.onTokenExpired = () => {
    void refreshOrSignOut(kc);
  };
}

/** Resolves once any existing session has been picked up. */
export async function initAuth(): Promise<void> {
  if (!keycloak) return;
  await keycloak.init({
    // The page is readable signed-out, so pick up an existing session without
    // forcing a login. The check runs in a hidden iframe, falling back to a
    // redirect where the browser blocks third-party cookies.
    onLoad: "check-sso",
    silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
    pkceMethod: "S256",
    checkLoginIframe: false,
  });
}

/** A token valid for at least 30 seconds, or undefined when signed out. */
export async function getToken(): Promise<string | undefined> {
  if (!keycloak?.authenticated) return undefined;
  if (!(await refreshOrSignOut(keycloak))) return undefined;
  return keycloak.token;
}

export function login(): void {
  void keycloak?.login();
}

export function logout(): void {
  void keycloak?.logout({ redirectUri: `${window.location.origin}/` });
}
