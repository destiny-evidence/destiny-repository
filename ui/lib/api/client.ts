// Shared API client for Destiny Repository UI

import axios from "axios";
import { getBaseApiUrl, getRuntimeConfig } from "../runtimeConfig";

export type ApiError = { type: "validation" | "generic"; detail: string };
export type ApiResult<T> = { data: T | null; error: ApiError | null };

async function buildHeaders(token?: string) {
  const cfg = await getRuntimeConfig();
  const isLocal = cfg["env"] === "local";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (!isLocal && token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export async function apiGet<T>(
  path: string,
  token?: string,
): Promise<ApiResult<T>> {
  const base = getBaseApiUrl() || "";
  const url = `${base.replace(/\/+$/, "")}${path}`;
  try {
    const resp = await axios.get(url, { headers: await buildHeaders(token) });
    return { data: resp.data as T, error: null };
  } catch (err: any) {
    if (err?.response?.status === 422 || err?.response?.status === 400) {
      return {
        data: null,
        error: {
          type: "validation",
          detail: err.response.data?.detail || "Validation error",
        },
      };
    }
    return {
      data: null,
      error: {
        type: "generic",
        detail: err?.response?.data?.detail || "API error",
      },
    };
  }
}
