// Types for Reference API

export interface ReferenceLookupParams {
  identifier: string;
  identifierType: string;
  otherIdentifierName?: string;
}

export interface ApiError {
  type: "validation" | "generic" | "not_found";
  detail: string;
}

export interface ReferenceLookupResult {
  data: any;
  error: ApiError | null;
}

// Search API types

export interface SearchResultTotal {
  count: number;
  is_lower_bound: boolean;
}

export interface SearchResultPage {
  count: number;
  number: number;
}

export interface Reference {
  id: string;
  visibility: string;
  identifiers: any[] | null;
  enhancements: any[] | null;
}

export interface ReferenceSearchResult {
  total: SearchResultTotal;
  page: SearchResultPage;
  references: Reference[];
}

export interface SearchApiResult {
  data?: ReferenceSearchResult;
  error?: ApiError;
}
