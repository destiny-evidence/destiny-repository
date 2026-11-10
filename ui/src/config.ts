// Trailing slashes are stripped so endpoints can always start with "/".
export const API_BASE = (
  import.meta.env.VITE_API_BASE || "http://localhost:8000/v1"
).replace(/\/+$/, "");

// Local development only: pairs with an API running with ENV=local, which
// bypasses auth itself.
export const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

export const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL;
export const KEYCLOAK_REALM = import.meta.env.VITE_KEYCLOAK_REALM;
export const KEYCLOAK_CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID;
