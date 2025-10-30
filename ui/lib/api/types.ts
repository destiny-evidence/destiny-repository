// Types for Reference API

export interface ReferenceLookupParams {
  identifier: string;
  identifierType: string;
  otherIdentifierName?: string;
}

export interface ReferenceLookupResult {
  data: any;
  error: null | {
    type: "validation" | "generic";
    detail: string;
  };
}
