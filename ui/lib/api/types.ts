// Types for Reference API

export interface ReferenceLookupParams {
  identifier: string;
  identifierType: string;
  otherIdentifierName?: string;
}

export interface ReferenceLookupResult {
  data: any;
  error: null | {
    type: "validation" | "generic" | "not_found";
    detail: string;
  };
}

export interface SearchParams {
  query: string;
  page?: number;
  startYear?: number;
  endYear?: number;
  annotations?: string[];
  sort?: string[];
}

export interface SearchResult {
  data?: {
    references: any[];
    total: {
      count: number;
      is_lower_bound: boolean;
    };
    page: {
      count: number;
      number: number;
    };
  };
  error: null | {
    type: "validation" | "generic" | "not_found";
    detail: string;
  };
}
