"use client";

import React, { useState, useEffect } from "react";
import ReferenceDisplay from "./ReferenceDisplay";
import JsonDisplay from "./JsonDisplay";
import { ReferenceSearchResult } from "../../lib/api/types";

interface SearchResultsProps {
  results: ReferenceSearchResult;
}

export default function SearchResults({ results }: SearchResultsProps) {
  const [tab, setTab] = useState<"visual" | "json">("visual");
  const [collapsedStates, setCollapsedStates] = useState<{
    [key: number]: boolean;
  }>({});

  const references = results.references;
  const totalCount = results.total.count;
  const isLowerBound = results.total.is_lower_bound;

  useEffect(() => {
    if (references && references.length > 0) {
      const initialStates: { [key: number]: boolean } = {};
      references.forEach((_, idx) => {
        initialStates[idx] = references.length > 1;
      });
      setCollapsedStates(initialStates);
    }
  }, [references]);

  function handleDownload() {
    const jsonlContent = references
      .map((result) => JSON.stringify(result))
      .join("\n");
    const blob = new Blob([jsonlContent], {
      type: "application/jsonl",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `search-results-${
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

  if (!references || references.length === 0) {
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
        <h3>No results found</h3>
        <p>Try adjusting your search query.</p>
      </div>
    );
  }

  const totalDisplay = isLowerBound
    ? `>${totalCount.toLocaleString()}`
    : totalCount.toLocaleString();

  return (
    <div style={{ marginTop: 24 }}>
      <div
        style={{
          marginBottom: 16,
          fontSize: "0.9rem",
          color: "#666",
        }}
      >
        {totalDisplay} result{totalCount !== 1 ? "s" : ""} found
      </div>
      <div className="tabs">
        <div className="tab-group">
          <button
            className={`tab ${tab === "visual" ? "active" : ""}`}
            onClick={() => setTab("visual")}
          >
            Visual ({references.length} on this page)
          </button>
          <button
            className={`tab ${tab === "json" ? "active" : ""}`}
            onClick={() => setTab("json")}
          >
            Raw
          </button>
        </div>
        {tab === "json" && (
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={handleDownload} title="Download as JSONL file">
              Download JSONL
            </button>
          </div>
        )}
      </div>
      <div className="multi-reference-container">
        {tab === "visual" ? (
          <div
            className={`multi-reference-visual ${
              references.length === 1 ? "single" : ""
            }`}
          >
            {references.map((result, idx) => (
              <ReferenceDisplay
                key={result?.id || idx}
                result={result}
                isCollapsed={collapsedStates[idx]}
                onToggle={() => toggleCollapsed(idx)}
              />
            ))}
          </div>
        ) : (
          <div style={{ padding: 16 }}>
            <JsonDisplay data={references} showCopyButton={true} />
          </div>
        )}
      </div>
    </div>
  );
}
