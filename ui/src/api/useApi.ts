// Hook for Destiny Repository API access

import { useAuth } from "@/auth/AuthContext";
import { getToken } from "@/auth/keycloak";
import { apiGet, ApiResult } from "./client";
import { ReferenceLookupResult, SearchParams, SearchResult } from "./types";

export function useApi() {
  const { authenticated: isLoggedIn } = useAuth();

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

  return { fetchReferences, searchReferences, isLoggedIn };
}
