// Base component for displaying multiple references with shared logic

import React, { useState } from "react";
import ReferenceDisplay from "./ReferenceDisplay";
import JsonDisplay from "./JsonDisplay";

interface BaseReferenceDisplayProps {
  references: any[];
  visualTabLabel: string;
  downloadFilename: string;
  emptyStateTitle?: string;
  emptyStateMessage?: string;
  searchedIdentifiers?: string[];
  showSearchedIdentifiers?: boolean;
  headerContent?: React.ReactNode;
  jsonData?: any; // Allow overriding what gets displayed in JSON tab
}

export default function BaseReferenceDisplay({
  references,
  visualTabLabel,
  downloadFilename,
  emptyStateTitle = "No references loaded yet",
  emptyStateMessage = "Please search for references to display their details.",
  searchedIdentifiers = [],
  showSearchedIdentifiers = false,
  headerContent,
  jsonData,
}: BaseReferenceDisplayProps) {
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

    references?.forEach((result) => {
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
  }, [searchedIdentifiers, references]);

  // Initialize all references as collapsed (except when there's only one)
  React.useEffect(() => {
    if (references && references.length > 0) {
      const initialStates: { [key: number]: boolean } = {};
      references.forEach((_, idx) => {
        // Auto-expand if there's only one reference, otherwise collapse all
        initialStates[idx] = references.length > 1; // true means collapsed
      });
      setCollapsedStates(initialStates);
    }
  }, [references]);

  function handleDownload() {
    const dataToDownload = jsonData || references;
    const content = Array.isArray(dataToDownload)
      ? dataToDownload.map((item) => JSON.stringify(item)).join("\n")
      : JSON.stringify(dataToDownload, null, 2);

    const blob = new Blob([content], {
      type: Array.isArray(dataToDownload)
        ? "application/jsonl"
        : "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadFilename;
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
      <div className="empty-state">
        <h3>{emptyStateTitle}</h3>
        <p>{emptyStateMessage}</p>
      </div>
    );
  }

  return (
    <div style={{ marginTop: 24 }}>
      {headerContent}
      <div className="tabs">
        <div className="tab-group">
          <button
            className={`tab ${tab === "visual" ? "active" : ""}`}
            onClick={() => setTab("visual")}
          >
            {visualTabLabel}
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
              Download{" "}
              {Array.isArray(jsonData || references) ? "JSONL" : "JSON"}
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
            {/* Unfound identifiers section */}
            {showSearchedIdentifiers && unfoundIdentifiers.length > 0 && (
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
            {references.map((result, idx) => (
              <ReferenceDisplay
                key={result?.id || idx}
                result={result}
                isCollapsed={collapsedStates[idx]}
                onToggle={() => toggleCollapsed(idx)}
                searchedIdentifiers={
                  showSearchedIdentifiers ? searchedIdentifiers : []
                }
              />
            ))}
          </div>
        ) : (
          <div style={{ padding: 16 }}>
            <JsonDisplay data={jsonData || references} showCopyButton={true} />
          </div>
        )}
      </div>
    </div>
  );
}
