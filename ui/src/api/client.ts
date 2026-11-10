// Shared API client for Destiny Repository UI

import { API_BASE } from "@/config";

export type ApiError = { type: "validation" | "generic"; detail: string };
export type ApiResult<T> = { data: T | null; error: ApiError | null };

// FastAPI reports request validation failures as a list of objects rather
// than a string, so normalise before anything tries to render it.
function readDetail(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail != null) return JSON.stringify(detail);
  return fallback;
}

export async function apiGet<T>(
  path: string,
  token?: string,
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { headers });
  } catch {
    return { data: null, error: { type: "generic", detail: "API error" } };
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    if (response.status === 422 || response.status === 400) {
      return {
        data: null,
        error: {
          type: "validation",
          detail: readDetail(body, "Validation error"),
        },
      };
    }
    return {
      data: null,
      error: { type: "generic", detail: readDetail(body, "API error") },
    };
  }

  return { data: (await response.json()) as T, error: null };
}
