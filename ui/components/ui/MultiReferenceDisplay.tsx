// MultiReferenceDisplay component for displaying multiple reference lookup results

import React, { useState } from "react";
import ReferenceDisplay from "./ReferenceDisplay";
import JsonDisplay from "./JsonDisplay";

interface MultiReferenceDisplayProps {
  results: any[];
}

export default function MultiReferenceDisplay({
  results,
}: MultiReferenceDisplayProps) {
  const [tab, setTab] = useState<"visual" | "json">("visual");
  const [collapsedStates, setCollapsedStates] = useState<{
    [key: number]: boolean;
  }>({});

  // Initialize all references as collapsed (except when there's only one)
  React.useEffect(() => {
    if (results && results.length > 0) {
      const initialStates: { [key: number]: boolean } = {};
      results.forEach((_, idx) => {
        // Auto-expand if there's only one reference, otherwise collapse all
        initialStates[idx] = results.length > 1; // true means collapsed
      });
      setCollapsedStates(initialStates);
    }
  }, [results]);

  function handleDownload() {
    const jsonlContent = results
      .map((result) => JSON.stringify(result))
      .join("\n");
    const blob = new Blob([jsonlContent], {
      type: "application/jsonl",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `references-bulk-${
      new Date().toISOString().split("T")[0]
    }.jsonl`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function toggleCollapsed(idx: number) {
    setCollapsedStates((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  }

  if (!results || results.length === 0) {
    return (
      <div
        style={{
          marginTop: 24,
          padding: "24px",
          background: "#f8f9fa",
          border: "1px solid #eee",
          borderRadius: "var(--border-radius)",
          color: "#555",
          textAlign: "center",
        }}
      >
        <h3>No references loaded yet</h3>
        <p>Please search for references to display their details.</p>
      </div>
    );
  }

  return (
    <div style={{ marginTop: 24 }}>
      <div className="multi-reference-tabs">
        <div className="multi-reference-tab-group">
          <button
            className={`multi-reference-tab ${
              tab === "visual" ? "active" : ""
            }`}
            onClick={() => setTab("visual")}
          >
            Visual ({results.length} reference{results.length !== 1 ? "s" : ""})
          </button>
          <button
            className={`multi-reference-tab ${tab === "json" ? "active" : ""}`}
            onClick={() => setTab("json")}
          >
            Raw
          </button>
        </div>
        {tab === "json" && (
          <div className="multi-reference-actions">
            <button
              className="multi-reference-action-btn"
              onClick={handleDownload}
              title="Download as JSONL file"
            >
              Download JSONL
            </button>
          </div>
        )}
      </div>
      <div className="multi-reference-container">
        {tab === "visual" ? (
          <div
            className={`multi-reference-visual ${
              results.length === 1 ? "single" : ""
            }`}
          >
            {results.map((result, idx) => (
              <ReferenceDisplay
                key={result?.id || idx}
                result={result}
                isCollapsed={collapsedStates[idx]}
                onToggle={() => toggleCollapsed(idx)}
              />
            ))}
          </div>
        ) : (
          <div className="multi-reference-json-container">
            <JsonDisplay
              data={results}
              className="multi-reference-json-display"
              showCopyButton={true}
            />
          </div>
        )}
      </div>
    </div>
  );
}
