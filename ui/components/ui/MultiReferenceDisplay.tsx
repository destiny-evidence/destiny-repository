// MultiReferenceDisplay component for displaying multiple reference lookup results

import React, { useState } from "react";
import ReferenceDisplay from "./ReferenceDisplay";
import JsonDisplay from "./JsonDisplay";

interface MultiReferenceDisplayProps {
  results: any[];
  searchedIdentifiers?: string[];
}

export default function MultiReferenceDisplay({
  results,
  searchedIdentifiers = [],
}: MultiReferenceDisplayProps) {
  const [tab, setTab] = useState<"visual" | "json">("visual");
  const [collapsedStates, setCollapsedStates] = useState<{
    [key: number]: boolean;
  }>({});
  const [unfoundCollapsed, setUnfoundCollapsed] = useState(false);

  // Detect unfound identifiers
  const unfoundIdentifiers = React.useMemo(() => {
    if (searchedIdentifiers.length === 0) return [];

    // Collect all identifiers found in the results
    const foundIdentifierStrings = new Set<string>();

    results?.forEach((result) => {
      // Add the reference ID itself
      if (result.id) {
        foundIdentifierStrings.add(result.id);
      }

      // Add all external identifiers
      result.identifiers?.forEach((identifier: any) => {
        // Build identifier string in the format used by the search
        let identifierString: string;
        if (identifier.identifier_type === "other") {
          identifierString = `other:${identifier.other_identifier_name}:${identifier.identifier}`;
        } else {
          identifierString = `${identifier.identifier_type}:${identifier.identifier}`;
        }
        foundIdentifierStrings.add(identifierString);
      });
    });

    // Find searched identifiers that weren't found
    return searchedIdentifiers.filter(
      (searchedId) => !foundIdentifierStrings.has(searchedId),
    );
  }, [searchedIdentifiers, results]);

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
      <div className="tabs">
        <div className="tab-group">
          <button
            className={`tab ${tab === "visual" ? "active" : ""}`}
            onClick={() => setTab("visual")}
          >
            Visual ({results.length} reference{results.length !== 1 ? "s" : ""})
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
              results.length === 1 ? "single" : ""
            }`}
          >
            {/* Unfound identifiers section */}
            {unfoundIdentifiers.length > 0 && (
              <div
                className="collapsible-item unfound-identifiers"
                style={{ marginBottom: 16 }}
              >
                <div
                  className="reference-item-header"
                  onClick={() => setUnfoundCollapsed(!unfoundCollapsed)}
                >
                  <span>
                    <strong>
                      {unfoundIdentifiers.length} identifier
                      {unfoundIdentifiers.length !== 1 ? "s" : ""} not found
                    </strong>
                  </span>
                  <span className="reference-item-toggle">
                    {unfoundCollapsed ? "+" : "−"}
                  </span>
                </div>
                {!unfoundCollapsed && (
                  <div className="reference-item-content">
                    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                      {unfoundIdentifiers.map((identifier, idx) => (
                        <li
                          key={idx}
                          style={{
                            padding: "4px 0",
                            borderBottom:
                              idx < unfoundIdentifiers.length - 1
                                ? "1px solid #f5f5f5"
                                : "none",
                            fontFamily: "var(--mono)",
                            fontSize: "0.9em",
                          }}
                        >
                          {identifier}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {results.map((result, idx) => (
              <ReferenceDisplay
                key={result?.id || idx}
                result={result}
                isCollapsed={collapsedStates[idx]}
                onToggle={() => toggleCollapsed(idx)}
                searchedIdentifiers={searchedIdentifiers}
              />
            ))}
          </div>
        ) : (
          <div style={{ padding: 16 }}>
            <JsonDisplay data={results} showCopyButton={true} />
          </div>
        )}
      </div>
    </div>
  );
}
