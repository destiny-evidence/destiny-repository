// ErrorDisplay component for showing error messages

import React from "react";

interface ErrorDisplayProps {
  error: string | null;
  type?: "validation" | "generic";
}

export default function ErrorDisplay({
  error,
  type = "generic",
}: ErrorDisplayProps) {
  if (!error) return null;
  return (
    <div className="error">
      {type === "validation" ? "Validation Error: " : "Error: "}
      {error}
    </div>
  );
}
