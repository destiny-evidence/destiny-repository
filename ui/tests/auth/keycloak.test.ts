// Covers the token lifecycle against a stubbed keycloak-js, since a wrong
// branch here either leaks an expired token or silently signs users out.

const instance = vi.hoisted(() => ({
  authenticated: false,
  token: undefined as string | undefined,
  init: vi.fn(),
  updateToken: vi.fn(),
  clearToken: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  onTokenExpired: undefined as (() => void) | undefined,
}));

vi.mock("keycloak-js", () => ({
  default: vi.fn(() => instance),
}));

vi.mock("@/config", () => ({
  AUTH_DISABLED: false,
  KEYCLOAK_URL: "http://localhost:8080",
  KEYCLOAK_REALM: "destiny",
  KEYCLOAK_CLIENT_ID: "client",
}));

import { getToken, initAuth, logout } from "@/auth/keycloak";

describe("keycloak auth", () => {
  beforeEach(() => {
    instance.authenticated = false;
    instance.token = undefined;
    instance.init.mockReset().mockResolvedValue(false);
    instance.updateToken.mockReset().mockResolvedValue(true);
    instance.clearToken.mockReset();
    instance.logout.mockReset();
  });

  it("checks for an existing session without forcing a login", async () => {
    await initAuth();

    expect(instance.init).toHaveBeenCalledWith(
      expect.objectContaining({
        onLoad: "check-sso",
        pkceMethod: "S256",
        silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
      }),
    );
  });

  it("returns no token when signed out", async () => {
    expect(await getToken()).toBeUndefined();
    expect(instance.updateToken).not.toHaveBeenCalled();
  });

  it("refreshes before returning the token", async () => {
    instance.authenticated = true;
    instance.updateToken.mockImplementation(async () => {
      instance.token = "fresh";
      return true;
    });

    expect(await getToken()).toBe("fresh");
    expect(instance.updateToken).toHaveBeenCalledWith(30);
  });

  it("drops the session when the refresh fails", async () => {
    instance.authenticated = true;
    instance.token = "stale";
    instance.updateToken.mockRejectedValue(new Error("expired"));

    expect(await getToken()).toBeUndefined();
    expect(instance.clearToken).toHaveBeenCalled();
  });

  it("refreshes when keycloak reports the token expired", async () => {
    instance.onTokenExpired?.();

    expect(instance.updateToken).toHaveBeenCalledWith(30);
  });

  it("returns to the home page after logout", () => {
    logout();

    expect(instance.logout).toHaveBeenCalledWith({
      redirectUri: `${window.location.origin}/`,
    });
  });
});
