// MSAL configuration for Azure Web app registration (authorization code flow)

import { Configuration } from "@azure/msal-browser";

import { getRuntimeConfig } from "./runtimeConfig";

export async function createMsalConfig(): Promise<Configuration> {
  const runtime = await getRuntimeConfig();
  const redirectUri =
    typeof window !== "undefined"
      ? `${window.location.protocol}//${window.location.host}/`
      : process.env.NEXT_PUBLIC_AZURE_REDIRECT_URI || "";

  return {
    auth: {
      clientId:
        runtime.NEXT_PUBLIC_AZURE_CLIENT_ID ||
        process.env.NEXT_PUBLIC_AZURE_CLIENT_ID ||
        "",
      authority:
        runtime.AZURE_LOGIN_URL ||
        process.env.AZURE_LOGIN_URL ||
        `https://login.microsoftonline.com/${
          runtime.NEXT_PUBLIC_AZURE_TENANT_ID ||
          process.env.NEXT_PUBLIC_AZURE_TENANT_ID
        }`,
      redirectUri,
    },
    cache: {
      cacheLocation: "localStorage",
      storeAuthStateInCookie: false,
    },
  };
}

export async function getLoginRequest(): Promise<{ scopes: string[] }> {
  const runtime = await getRuntimeConfig();
  return {
    scopes: [
      "openid",
      "profile",
      `api://${
        runtime.NEXT_PUBLIC_AZURE_APPLICATION_ID ||
        process.env.NEXT_PUBLIC_AZURE_APPLICATION_ID
      }/reference.reader.all`,
    ],
  };
}
