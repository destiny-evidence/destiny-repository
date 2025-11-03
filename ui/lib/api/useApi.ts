// React hook for Destiny Repository API access

import React from "react";
import { useMsal } from "@azure/msal-react";
import { getLoginRequest } from "../msalConfig";
import { apiGet, ApiResult } from "./client";
import { ReferenceLookupResult } from "./types";
import { getRuntimeConfig } from "../runtimeConfig";
import { InteractionStatus } from "@azure/msal-browser";

export function useApi() {
  const { instance, accounts, inProgress } = useMsal();

  const [env, setEnv] = React.useState<string | undefined>(undefined);

  React.useEffect(() => {
    (async () => {
      try {
        const cfg = await getRuntimeConfig();
        console.log(cfg);
        setEnv(cfg["ENV"]);
      } catch (e) {
        console.warn("Failed to load runtime config", e);
      }
    })();
  }, []);

  const isLocal = env === "local";
  const isLoggedIn = isLocal || (accounts?.length ?? 0) > 0;
  const isLoginProcessing =
    inProgress === InteractionStatus.Login ||
    inProgress === InteractionStatus.AcquireToken ||
    inProgress === InteractionStatus.HandleRedirect ||
    inProgress === InteractionStatus.SsoSilent;

  async function getToken(): Promise<string | undefined> {
    if (!isLoggedIn || isLocal) return undefined;
    if (!accounts || accounts.length === 0) return undefined;

    try {
      const request = await getLoginRequest();
      const resp = await instance.acquireTokenSilent({
        ...request,
        account: accounts[0],
      });
      return resp?.accessToken;
    } catch (err: any) {
      console.warn(
        "acquireTokenSilent failed, starting redirect:",
        err?.message,
      );
      try {
        const request = await getLoginRequest();
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

  async function fetchReferences(
    identifiers: string[],
  ): Promise<ReferenceLookupResult> {
    try {
      const token = await getToken();
      const urlParams = new URLSearchParams();

      // Send identifiers as a comma-separated list in a single parameter
      urlParams.set("identifier", identifiers.join(","));

      const path = `/references/?${urlParams.toString()}`;
      const result: ApiResult<any> = await apiGet(path, token);

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
    } catch (err: any) {
      return {
        data: undefined,
        error: { type: "generic", detail: err?.message ?? "Unknown error" },
      };
    }
  }

  return { fetchReferences, isLoggedIn, isLoginProcessing };
}
