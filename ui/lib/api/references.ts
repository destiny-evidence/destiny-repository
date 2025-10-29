// Reference API module for Destiny Repository UI

import axios from "axios";
import { ReferenceLookupParams, ReferenceLookupResult } from "./types";

import { getBaseApiUrl } from "../runtimeConfig";

export async function fetchReference(
  params: ReferenceLookupParams,
  token: string,
): Promise<ReferenceLookupResult> {
  const baseUrl = getBaseApiUrl();

  let url: string;
  if (params.identifierType === "destiny_id") {
    url = `${baseUrl}references/${params.identifier}/`;
  } else {
    const urlParams = new URLSearchParams({
      identifier: params.identifier,
      identifier_type: params.identifierType,
    });
    if (params.otherIdentifierName) {
      urlParams.append("other_identifier_name", params.otherIdentifierName);
    }
    url = `${baseUrl}references/?${urlParams.toString()}`;
  }

  try {
    const response = await axios.get(url, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    return { data: response.data, error: null };
  } catch (err: any) {
    // 422 validation errors
    if (err?.response?.status === 422) {
      return {
        data: null,
        error: {
          type: "validation",
          detail: err.response.data?.detail || "Validation error",
        },
      };
    }
    // Other errors
    return {
      data: null,
      error: {
        type: "generic",
        detail: err?.response?.data?.detail || "Error fetching reference.",
      },
    };
  }
}
