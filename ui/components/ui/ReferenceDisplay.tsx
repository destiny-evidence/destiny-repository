// ReferenceDisplay component for displaying reference lookup results

import React, { useState } from "react";
import JsonDisplay from "./JsonDisplay";

interface ReferenceDisplayProps {
  result: any;
  isCollapsed: boolean;
  onToggle?: () => void;
}

// Helper function to generate a brief summary of a reference
function getReferenceSummary(refData: any): React.ReactNode {
  const identifiers = refData.identifiers.reduce(
    (acc: any, curr: any) => {
      acc[curr.identifier_type] = curr;
      return acc;
    },
    {} as { [key: string]: any },
  );

  const enhancementCount = refData.enhancements?.length || 0;
  const duplicateCount = 0;
  let summary = (
    <>
      <strong>
        {refData.id}: {enhancementCount} enhancement
        {enhancementCount !== 1 ? "s" : ""}
        {", "} {duplicateCount} duplicate{duplicateCount !== 1 ? "s" : ""}
      </strong>
      <div>
        {Object.values(identifiers).map((id: any, idx: number, arr: any[]) => (
          <span key={idx}>
            {id.other_identifier_name || id.identifier_type}: {id.identifier}
            {idx < arr.length - 1 && <span> | </span>}
          </span>
        ))}
      </div>
    </>
  );

  return summary;
}

function IdentifierDisplay({ identifiers }: { identifiers: any[] }) {
  if (!identifiers || identifiers.length === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <h3>Identifiers</h3>
      <ul className="reference-identifiers">
        {identifiers.map((id, idx) => {
          if (id.identifier_type === "doi") {
            return (
              <li key={idx}>
                DOI:{" "}
                <a
                  href={`https://doi.org/${id.identifier}`}
                  target="_blank"
                  rel="noopener noreferrer"
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
                >
                  {id.identifier}
                </a>
              </li>
            );
          }
          if (id.identifier_type === "other") {
            return (
              <li key={idx}>
                {id.other_identifier_name}: {id.identifier}
              </li>
            );
          }
          return (
            <li key={idx}>
              {id.identifier_type}: {id.identifier}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EnhancementDisplay({ enhancements }: { enhancements: any[] }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  if (!enhancements || enhancements.length === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <h3>Enhancements</h3>
      <div>
        {enhancements.map((enh, idx) => (
          <div key={idx} className="enhancement-item">
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
        ))}
      </div>
    </div>
  );
}

export default function ReferenceDisplay({
  result,
  isCollapsed,
  onToggle,
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
    <div className="reference-item">
      <div className="reference-item-header" onClick={onToggle}>
        <span>{getReferenceSummary(refData)}</span>
        <span className="reference-item-toggle">{isCollapsed ? "+" : "−"}</span>
      </div>
      {!isCollapsed && (
        <div className="reference-item-content">
          <div style={{ marginBottom: 16 }}>
            <h4>ID: {refData.id}</h4>
          </div>
          <IdentifierDisplay identifiers={refData.identifiers || []} />
          <EnhancementDisplay enhancements={refData.enhancements || []} />
        </div>
      )}
    </div>
  );
}
