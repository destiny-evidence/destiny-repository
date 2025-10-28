// MSAL configuration for Azure Web app registration (authorization code flow)

import { Configuration } from "@azure/msal-browser";

export function createMsalConfig(): Configuration {
  const redirectUri =
    typeof window !== "undefined"
      ? `${window.location.protocol}//${window.location.host}/`
      : process.env.NEXT_PUBLIC_AZURE_REDIRECT_URI || "";

  return {
    auth: {
      clientId: process.env.NEXT_PUBLIC_AZURE_CLIENT_ID || "",
      authority: `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_AZURE_TENANT_ID}`,
      redirectUri,
    },
    cache: {
      cacheLocation: "localStorage",
      storeAuthStateInCookie: false,
    },
  };
}

export const loginRequest = {
  scopes: [
    "openid",
    "profile",
    `api://${process.env.NEXT_PUBLIC_AZURE_APPLICATION_ID}/reference.reader.all`,
  ],
};
