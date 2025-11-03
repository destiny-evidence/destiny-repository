// ReferenceDisplay component for displaying reference lookup results

import React, { useState } from "react";
import JsonDisplay from "./JsonDisplay";

interface ReferenceDisplayProps {
  result: any;
  isCollapsed: boolean;
  onToggle?: () => void;
}

// Helper function to generate a brief summary of a reference
function getReferenceSummary(refData: any): string {
  if (!refData) return "Unknown reference";

  const identifiers = refData.identifiers || [];
  const doi = identifiers.find((id: any) => id.identifier_type === "doi");
  const pmid = identifiers.find((id: any) => id.identifier_type === "pm_id");
  const openAlex = identifiers.find(
    (id: any) => id.identifier_type === "open_alex",
  );

  let summary = `ID: ${refData.id}`;

  if (doi) {
    summary += ` | DOI: ${doi.identifier}`;
  }
  if (pmid) {
    summary += ` | PubMed: ${pmid.identifier}`;
  }
  if (openAlex) {
    summary += ` | OpenAlex: ${openAlex.identifier.split("/").pop()}`;
  }

  const enhancementCount = refData.enhancements?.length || 0;
  summary += ` | ${enhancementCount} enhancement${
    enhancementCount !== 1 ? "s" : ""
  }`;

  return summary;
}

function IdentifierDisplay({ identifiers }: { identifiers: any[] }) {
  if (!identifiers || identifiers.length === 0) return null;
  return (
    <div className="reference-section">
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
    <div className="reference-section">
      <h3>Enhancements</h3>
      <div>
        {enhancements.map((enh, idx) => (
          <div key={idx} className="enhancement-item">
            <div
              className="enhancement-header"
              onClick={() => setOpenIdx(openIdx === idx ? null : idx)}
            >
              <span className="enhancement-summary">
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
                  maxHeight="300px"
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
        <span className="reference-item-summary">
          {getReferenceSummary(refData)}
        </span>
        <span className="reference-item-toggle">{isCollapsed ? "+" : "−"}</span>
      </div>
      {!isCollapsed && (
        <div className="reference-item-content">
          <div className="reference-section">
            <h4>ID: {refData.id}</h4>
          </div>
          <IdentifierDisplay identifiers={refData.identifiers || []} />
          <EnhancementDisplay enhancements={refData.enhancements || []} />
        </div>
      )}
    </div>
  );
}
