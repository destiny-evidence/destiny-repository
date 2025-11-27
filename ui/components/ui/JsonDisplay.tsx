// JsonDisplay component for displaying JSON content with copy functionality

import React from "react";

interface JsonDisplayProps {
  data: any;
  title?: string;
  showCopyButton?: boolean;
  maxHeight?: string;
  className?: string;
}

export default function JsonDisplay({
  data,
  title,
  showCopyButton = false,
  className = "",
}: JsonDisplayProps) {
  function handleCopy() {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
  }

  return (
    <div className={`json-display ${className}`}>
      {(title || showCopyButton) && (
        <div className="json-display-header">
          <span className="json-display-title">{title}</span>
          {showCopyButton && (
            <button
              className="json-display-copy-btn"
              onClick={handleCopy}
              title="Copy JSON to clipboard"
            >
              Copy
            </button>
          )}
        </div>
      )}
      <pre className="json-display-content">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
