// ErrorDisplay component for showing error messages

import React from "react";

interface ErrorDisplayProps {
  error: string | null;
  type?: "validation" | "generic";
}

function parseElasticsearchError(errorMessage: string): {
  title: string;
  message: string;
  details?: string;
} {
  // Check if it's an Elasticsearch query string error
  const esMatch = errorMessage.match(
    /Elasticsearch query string search failed: (\w+)\((\d+), '([^']+)', '([^']+)'\)/,
  );

  if (esMatch) {
    const [, errorType, statusCode, errorName, errorDetail] = esMatch;
    return {
      title: "Query Syntax Error",
      message: errorDetail,
      details: `${errorName} (${statusCode})`,
    };
  }

  // Default parsing
  return {
    title: "Error",
    message: errorMessage,
  };
}

export default function ErrorDisplay({
  error,
  type = "generic",
}: ErrorDisplayProps) {
  if (!error) return null;

  const parsed = type === "validation" ? parseElasticsearchError(error) : null;

  if (parsed) {
    return (
      <div className="error-display">
        <div className="error-title">{parsed.title}</div>
        <div className="error-message">{parsed.message}</div>
        {parsed.details && (
          <div className="error-details">{parsed.details}</div>
        )}
      </div>
    );
  }

  return (
    <div className="error">
      {type === "validation" ? "Validation Error: " : "Error: "}
      {error}
    </div>
  );
}
