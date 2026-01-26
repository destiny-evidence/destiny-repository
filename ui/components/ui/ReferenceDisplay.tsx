// ReferenceDisplay component for displaying reference lookup results

import React, { useState } from "react";
import JsonDisplay from "./JsonDisplay";

// Encode DOI path segments for use in URLs, preserving "/" separators
const encodeDoiPath = (doi: string): string =>
  doi.split("/").map(encodeURIComponent).join("/");

interface ReferenceDisplayProps {
  result: any;
  isCollapsed: boolean;
  onToggle?: () => void;
  searchedIdentifiers?: string[];
}

// Helper function to generate a brief summary of a reference
function getReferenceSummary(
  refData: any,
  searchedIdentifiers: string[] = [],
): React.ReactNode {
  // Check if the reference ID itself was searched for
  const isIdSearched = searchedIdentifiers.includes(refData.id);

  // Group all identifiers by type
  const identifiersByType: { [key: string]: any[] } = {};
  (refData.identifiers || []).forEach((id: any) => {
    if (!identifiersByType[id.identifier_type]) {
      identifiersByType[id.identifier_type] = [];
    }
    identifiersByType[id.identifier_type].push(id);
  });

  const enhancementCount = refData.enhancements?.length || 0;

  // Count unique duplicate reference IDs
  const duplicateReferenceIds = new Set<string>();
  (refData.enhancements || []).forEach((enh: any) => {
    if (enh.reference_id !== refData.id) {
      duplicateReferenceIds.add(enh.reference_id);
    }
  });
  const duplicateCount = duplicateReferenceIds.size;

  let summary = (
    <>
      <strong>
        <span style={isIdSearched ? { textDecoration: "underline" } : {}}>
          {refData.id}
        </span>
        : {enhancementCount} enhancement
        {enhancementCount !== 1 ? "s" : ""}
        {", "} {duplicateCount} duplicate{duplicateCount !== 1 ? "s" : ""}
      </strong>
      <div>
        {Object.entries(identifiersByType).map(([type, ids], typeIdx) => (
          <div key={typeIdx} style={{ marginBottom: 4 }}>
            <span style={{ fontWeight: 500 }}>{type}:</span>{" "}
            {ids.map((id: any, idx: number) => {
              // Check if this identifier was searched for
              let identifierString: string;
              if (id.identifier_type === "other") {
                identifierString = `other:${id.other_identifier_name}:${id.identifier}`;
              } else {
                identifierString = `${id.identifier_type}:${id.identifier}`;
              }
              const isSearched = searchedIdentifiers.includes(identifierString);

              return (
                <span key={idx}>
                  <span
                    style={isSearched ? { textDecoration: "underline" } : {}}
                  >
                    {id.other_identifier_name
                      ? `${id.other_identifier_name}: `
                      : ""}
                    {id.identifier}
                  </span>
                  {idx < ids.length - 1 && <span> | </span>}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </>
  );

  return summary;
}

function IdentifierDisplay({
  identifiers,
  referenceId,
  searchedIdentifiers = [],
}: {
  identifiers: any[];
  referenceId: string;
  searchedIdentifiers?: string[];
}) {
  if (!identifiers || identifiers.length === 0) return null;

  // Track which identifier values have already been shown
  const shown = new Set<string>();

  // Helper function to check if an identifier was searched for
  const isSearchedIdentifier = (identifier: any): boolean => {
    let identifierString: string;
    if (identifier.identifier_type === "other") {
      identifierString = `other:${identifier.other_identifier_name}:${identifier.identifier}`;
    } else {
      identifierString = `${identifier.identifier_type}:${identifier.identifier}`;
    }
    return searchedIdentifiers.includes(identifierString);
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <h3>Identifiers</h3>
      <ul className="reference-identifiers">
        {identifiers
          .sort((a, b) => {
            // Primary: identifier_type, with 'other' always last
            if (a.identifier_type === "other" && b.identifier_type !== "other")
              return 1;
            if (b.identifier_type === "other" && a.identifier_type !== "other")
              return -1;
            if (a.identifier_type !== b.identifier_type) {
              return a.identifier_type.localeCompare(b.identifier_type);
            }
            // Secondary: other_identifier_name (only relevant for 'other', but safe for all)
            const aOther = a.other_identifier_name || "";
            const bOther = b.other_identifier_name || "";
            if (aOther !== bOther) {
              return aOther.localeCompare(bOther);
            }
            // Tertiary: identifier
            return String(a.identifier).localeCompare(String(b.identifier));
          })
          .map((id, idx) => {
            // Only show if not already shown
            const uniqueKey = `${id.identifier_type}:${id.other_identifier_name}:${id.identifier}`;
            if (shown.has(uniqueKey)) return null;
            shown.add(uniqueKey);

            const isSearched = isSearchedIdentifier(id);
            const linkStyle = isSearched ? { textDecoration: "underline" } : {};

            if (id.identifier_type === "doi") {
              return (
                <li key={idx}>
                  DOI:{" "}
                  <a
                    href={`https://doi.org/${encodeDoiPath(id.identifier)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={linkStyle}
                  >
                    {id.identifier}
                  </a>
                </li>
              );
            }
            if (id.identifier_type === "pm_id") {
              return (
                <li key={idx}>
                  PubMed:{" "}
                  <a
                    href={`https://pubmed.ncbi.nlm.nih.gov/${id.identifier}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={linkStyle}
                  >
                    {id.identifier}
                  </a>
                </li>
              );
            }
            if (id.identifier_type === "open_alex") {
              return (
                <li key={idx}>
                  OpenAlex:{" "}
                  <a
                    href={`https://openalex.org/${id.identifier}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={linkStyle}
                  >
                    {id.identifier}
                  </a>
                </li>
              );
            }
            if (id.identifier_type === "other") {
              return (
                <li key={idx}>
                  <span
                    style={isSearched ? { textDecoration: "underline" } : {}}
                  >
                    {id.other_identifier_name}: {id.identifier}
                  </span>
                </li>
              );
            }
            return (
              <li key={idx}>
                <span style={isSearched ? { textDecoration: "underline" } : {}}>
                  {id.identifier_type}: {id.identifier}
                </span>
              </li>
            );
          })}
      </ul>
    </div>
  );
}

function EnhancementDisplay({
  enhancements,
  referenceId,
}: {
  enhancements: any[];
  referenceId: string;
}) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  if (!enhancements || enhancements.length === 0) return null;

  // Sort enhancements: non-duplicates first, then duplicates
  const sortedEnhancements = [...enhancements].sort((a, b) => {
    const aIsDuplicate = a.reference_id !== referenceId;
    const bIsDuplicate = b.reference_id !== referenceId;
    if (aIsDuplicate === bIsDuplicate) return 0;
    return aIsDuplicate ? 1 : -1;
  });

  return (
    <div style={{ marginBottom: 16 }}>
      <h3>Enhancements</h3>
      <div>
        {sortedEnhancements.map((enh, idx) => {
          const isDuplicate = enh.reference_id !== referenceId;
          return (
            <div key={idx} className="collapsible-item">
              <div
                className="enhancement-header"
                onClick={() => setOpenIdx(openIdx === idx ? null : idx)}
              >
                <span>
                  <strong>
                    {enh.content?.enhancement_type || "Enhancement"}
                  </strong>
                  {" | "}Source: {enh.source}
                  {" | "}Robot Version: {enh.robot_version}
                  {isDuplicate && (
                    <span className="duplicate-note">(from duplicate)</span>
                  )}
                </span>
                <span className="enhancement-toggle">
                  {openIdx === idx ? "−" : "+"}
                </span>
              </div>
              {openIdx === idx && (
                <div className="enhancement-content">
                  <JsonDisplay
                    data={enh}
                    title="Enhancement Details"
                    showCopyButton={true}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ReferenceDisplay({
  result,
  isCollapsed,
  onToggle,
  searchedIdentifiers = [],
}: ReferenceDisplayProps) {
  const refData = result;

  if (!refData) {
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
        <h3>No reference loaded yet</h3>
        <p>Please search for a reference to display its details.</p>
      </div>
    );
  }

  return (
    <div className="collapsible-item">
      <div className="reference-item-header" onClick={onToggle}>
        <span>{getReferenceSummary(refData, searchedIdentifiers)}</span>
        <span className="reference-item-toggle">{isCollapsed ? "+" : "−"}</span>
      </div>
      {!isCollapsed && (
        <div className="reference-item-content">
          <div style={{ marginBottom: 16 }}>
            <h4>
              ID:{" "}
              <span
                style={
                  searchedIdentifiers.includes(refData.id)
                    ? { textDecoration: "underline" }
                    : {}
                }
              >
                {refData.id}
              </span>
            </h4>
          </div>
          <IdentifierDisplay
            identifiers={refData.identifiers || []}
            referenceId={refData.id}
            searchedIdentifiers={searchedIdentifiers}
          />
          <EnhancementDisplay
            enhancements={refData.enhancements || []}
            referenceId={refData.id}
          />
        </div>
      )}
    </div>
  );
}
