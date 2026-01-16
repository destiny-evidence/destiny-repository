// React hook for Destiny Repository API access - supports Azure AD and Keycloak

import { createContext, useContext } from "react";
import { useMsal } from "@azure/msal-react";
import { useAuth } from "react-oidc-context";
import { InteractionStatus } from "@azure/msal-browser";
import { getMsalLoginRequest, AuthProvider } from "../authConfig";
import { apiGet, ApiResult } from "./client";
import { ReferenceLookupResult, SearchParams, SearchResult } from "./types";

/**
 * Context to provide the auth provider from layout.
 */
export const AuthProviderContext = createContext<AuthProvider>("local");

/**
 * Hook for Azure AD (MSAL) authentication.
 * Called unconditionally but only uses MSAL when enabled.
 */
function useAzureAuth(enabled: boolean) {
  // useMsal must be called unconditionally to maintain hook order.
  // When not in MSAL context, it returns safe defaults.
  let instance: ReturnType<typeof useMsal>["instance"] | null = null;
  let accounts: ReturnType<typeof useMsal>["accounts"] = [];
  let inProgress: ReturnType<typeof useMsal>["inProgress"] =
    InteractionStatus.None;

  try {
    const msal = useMsal();
    instance = msal.instance;
    accounts = msal.accounts;
    inProgress = msal.inProgress;
  } catch {
    // Not in MSAL context - use defaults
  }

  const isLoggedIn = enabled && (accounts?.length ?? 0) > 0;
  const isLoginProcessing =
    enabled &&
    (inProgress === InteractionStatus.Login ||
      inProgress === InteractionStatus.AcquireToken ||
      inProgress === InteractionStatus.HandleRedirect ||
      inProgress === InteractionStatus.SsoSilent);

  async function getToken(): Promise<string | undefined> {
    if (!enabled || !instance || !accounts || accounts.length === 0)
      return undefined;

    try {
      const request = await getMsalLoginRequest();
      const resp = await instance.acquireTokenSilent({
        ...request,
        account: accounts[0],
      });
      return resp?.accessToken;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.warn("acquireTokenSilent failed, starting redirect:", message);
      try {
        const request = await getMsalLoginRequest();
        instance.acquireTokenRedirect({
          ...request,
          account: accounts[0],
        });
      } catch (redirectErr) {
        console.error("acquireTokenRedirect failed:", redirectErr);
      }
      return undefined;
    }
  }

  return { getToken, isLoggedIn, isLoginProcessing };
}

/**
 * Hook for Keycloak (OIDC) authentication.
 * Called unconditionally but only uses OIDC when enabled.
 */
function useKeycloakAuth(enabled: boolean) {
  // useAuth must be called unconditionally to maintain hook order.
  // When not in OIDC context, it throws - we catch and use defaults.
  let auth: ReturnType<typeof useAuth> | null = null;

  try {
    auth = useAuth();
  } catch {
    // Not in OIDC context - use defaults
  }

  const isLoggedIn = enabled && (auth?.isAuthenticated ?? false);
  const isLoginProcessing = enabled && (auth?.isLoading ?? false);

  async function getToken(): Promise<string | undefined> {
    if (!enabled || !auth?.isAuthenticated || !auth.user) return undefined;
    return auth.user.access_token;
  }

  return { getToken, isLoggedIn, isLoginProcessing };
}

/**
 * Hook for local development (no auth).
 */
function useLocalAuth() {
  return {
    getToken: async () => undefined,
    isLoggedIn: true, // Always "logged in" locally
    isLoginProcessing: false,
  };
}

export function useApi() {
  // Get provider from context - this is set synchronously by layout after initialization
  const provider = useContext(AuthProviderContext);

  const isLocal = provider === "local";

  // Always call hooks unconditionally based on provider from context.
  // The layout ensures children only render when inside the correct provider context.
  const azureAuth = useAzureAuth(provider === "azure");
  const keycloakAuth = useKeycloakAuth(provider === "keycloak");
  const localAuth = useLocalAuth();

  // Select the appropriate auth based on provider
  const auth =
    provider === "azure"
      ? azureAuth
      : provider === "keycloak"
        ? keycloakAuth
        : localAuth;

  async function getToken(): Promise<string | undefined> {
    if (isLocal) return undefined;
    return auth.getToken();
  }

  const isLoggedIn = isLocal || auth.isLoggedIn;
  const isLoginProcessing = auth.isLoginProcessing;

  async function fetchReferences(
    identifiers: string[],
  ): Promise<ReferenceLookupResult> {
    try {
      const token = await getToken();
      const urlParams = new URLSearchParams();

      // Send identifiers as a comma-separated list in a single parameter
      urlParams.set("identifier", identifiers.join(","));

      const path = `/references/?${urlParams.toString()}`;
      const result: ApiResult<unknown> = await apiGet(path, token);

      const dataArr = Array.isArray(result.data) ? result.data : [];
      if (dataArr.length === 0 && !result.error) {
        return {
          data: undefined,
          error: { type: "not_found", detail: "No results found" },
        };
      }

      return {
        data: dataArr,
        error: result.error,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      return {
        data: undefined,
        error: { type: "generic", detail: message },
      };
    }
  }

  async function searchReferences(params: SearchParams): Promise<SearchResult> {
    try {
      const token = await getToken();
      const urlParams = new URLSearchParams();

      urlParams.set("q", params.query);
      if (params.page) urlParams.set("page", params.page.toString());
      if (params.startYear)
        urlParams.set("start_year", params.startYear.toString());
      if (params.endYear) urlParams.set("end_year", params.endYear.toString());
      if (params.annotations) {
        params.annotations.forEach((annotation) => {
          urlParams.append("annotation", annotation);
        });
      }
      if (params.sort) {
        params.sort.forEach((sortField) => {
          urlParams.append("sort", sortField);
        });
      }

      const path = `/references/search/?${urlParams.toString()}`;
      const result: ApiResult<SearchResult["data"]> = await apiGet(path, token);

      if (result.error) {
        return {
          data: undefined,
          error: result.error,
        };
      }

      if (!result.data || !result.data.references) {
        return {
          data: undefined,
          error: { type: "not_found", detail: "No results found" },
        };
      }

      return {
        data: result.data,
        error: null,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      return {
        data: undefined,
        error: { type: "generic", detail: message },
      };
    }
  }

  return { fetchReferences, searchReferences, isLoggedIn, isLoginProcessing };
}
