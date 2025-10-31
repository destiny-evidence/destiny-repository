// React hook for Destiny Repository API access

import React from "react";
import { useMsal } from "@azure/msal-react";
import { getLoginRequest } from "../msalConfig";
import { apiGet, ApiResult } from "./client";
import { ReferenceLookupParams, ReferenceLookupResult } from "./types";
import { getRuntimeConfig } from "../runtimeConfig";
import { InteractionStatus } from "@azure/msal-browser";

export function useApi() {
  const { instance, accounts, inProgress } = useMsal();

  const [env, setEnv] = React.useState<string | undefined>(undefined);

  React.useEffect(() => {
    (async () => {
      const cfg = await getRuntimeConfig();
      setEnv(cfg["env"]);
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
    if (!isLoggedIn) return undefined;
    if (isLocal) return undefined;
    const request = await getLoginRequest();
    const resp = await instance.acquireTokenSilent({
      ...request,
      account: accounts[0],
    });
    return resp?.accessToken;
  }

  async function fetchReference(
    params: ReferenceLookupParams,
  ): Promise<ReferenceLookupResult> {
    const token = await getToken();
    const urlParams = new URLSearchParams({});
    if (params.identifierType == "destiny_id") {
      urlParams.set("identifier", params.identifier);
    } else if (params.otherIdentifierName) {
      urlParams.set(
        "identifier",
        "other:" +
          params.otherIdentifierName +
          ":" +
          params.otherIdentifierName,
      );
    } else {
      urlParams.set(
        "identifier",
        params.identifierType + ":" + params.identifier,
      );
    }
    const path = `/references/?${urlParams.toString()}`;
    const result: ApiResult<any> = await apiGet(path, token);
    if (result.data.length === 0) {
      return {
        data: undefined,
        error: { type: "not_found", detail: "No results found" },
      };
    }
    return {
      data: result.data[0],
      error: result.error,
    };
  }

  return { fetchReference, isLoggedIn, isLoginProcessing };
}
