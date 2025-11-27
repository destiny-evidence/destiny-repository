// Utility functions for identifier formatting

export interface IdentifierParams {
  identifier: string;
  identifierType: string;
  otherIdentifierName?: string;
}

/**
 * Convert identifier parameters to colon format string
 * @param params - Identifier parameters from form
 * @returns Formatted identifier string (e.g., "doi:10.1234/abcd")
 */
export function toIdentifierString(params: IdentifierParams): string {
  if (params.identifierType === "destiny_id") {
    return params.identifier;
  } else if (params.otherIdentifierName) {
    return `other:${params.otherIdentifierName}:${params.identifier}`;
  } else {
    return `${params.identifierType}:${params.identifier}`;
  }
}
