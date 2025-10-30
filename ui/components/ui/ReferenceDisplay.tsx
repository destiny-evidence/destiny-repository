// ReferenceDisplay component for displaying reference lookup results

import React, { useState } from "react";

interface ReferenceDisplayProps {
  result: any;
}

function IdentifierDisplay({ identifiers }: { identifiers: any[] }) {
  if (!identifiers || identifiers.length === 0) return null;
  return (
    <section>
      <h3>Identifiers</h3>
      <ul>
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
    </section>
  );
}

function EnhancementDisplay({ enhancements }: { enhancements: any[] }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  if (!enhancements || enhancements.length === 0) return null;
  return (
    <section>
      <h3>Enhancements</h3>
      <div>
        {enhancements.map((enh, idx) => (
          <div
            key={idx}
            style={{
              border: "1px solid #eee",
              borderRadius: "var(--border-radius)",
              marginBottom: 12,
              background: "#fafafa",
              padding: "8px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                cursor: "pointer",
              }}
              onClick={() => setOpenIdx(openIdx === idx ? null : idx)}
            >
              <span>
                <strong>
                  {enh.content?.enhancement_type || "Enhancement"}
                </strong>
                {" | "}Source: {enh.source}
                {" | "}Robot Version: {enh.robot_version}
              </span>
              <span style={{ fontWeight: "bold", fontSize: 18 }}>
                {openIdx === idx ? "−" : "+"}
              </span>
            </div>
            {openIdx === idx && (
              <pre
                style={{
                  marginTop: 8,
                  background: "#fff",
                  border: "1px solid #eee",
                  borderRadius: "var(--border-radius)",
                  padding: "8px",
                  fontSize: "0.95em",
                  overflowX: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {JSON.stringify(enh, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function ReferenceDisplay({ result }: ReferenceDisplayProps) {
  const [tab, setTab] = useState<"visual" | "json">("visual");
  const refData = result;

  // Copy and download handlers
  function handleCopy() {
    navigator.clipboard.writeText(JSON.stringify(refData, null, 2));
  }
  function handleDownload() {
    const blob = new Blob([JSON.stringify(refData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reference-${refData.id}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

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
    <div style={{ marginTop: 24 }}>
      <div
        style={{
          marginBottom: 16,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <button
            style={{
              marginRight: 8,
              background: tab === "visual" ? "var(--primary-light)" : "#eee",
              color: tab === "visual" ? "#fff" : "var(--foreground)",
              border: "none",
              borderRadius: "var(--border-radius)",
              padding: "6px 16px",
              cursor: "pointer",
              fontWeight: tab === "visual" ? "bold" : "normal",
            }}
            onClick={() => setTab("visual")}
          >
            Visual
          </button>
          <button
            style={{
              background: tab === "json" ? "var(--primary-light)" : "#eee",
              color: tab === "json" ? "#fff" : "var(--foreground)",
              border: "none",
              borderRadius: "var(--border-radius)",
              padding: "6px 16px",
              cursor: "pointer",
              fontWeight: tab === "json" ? "bold" : "normal",
            }}
            onClick={() => setTab("json")}
          >
            JSON
          </button>
        </div>
        {tab === "json" && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              style={{
                background: "var(--primary-light)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--border-radius)",
                padding: "6px 16px",
                cursor: "pointer",
                fontWeight: "bold",
              }}
              onClick={handleCopy}
            >
              Copy
            </button>
            <button
              style={{
                background: "var(--primary-light)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--border-radius)",
                padding: "6px 16px",
                cursor: "pointer",
                fontWeight: "bold",
              }}
              onClick={handleDownload}
            >
              Download
            </button>
          </div>
        )}
      </div>
      <div className="reference-result-box">
        {tab === "visual" ? (
          <div>
            <section>
              <div>
                <h3>ID: {refData.id}</h3>
              </div>
            </section>
            <IdentifierDisplay identifiers={refData.identifiers || []} />
            <EnhancementDisplay enhancements={refData.enhancements || []} />
          </div>
        ) : (
          <div>
            <pre className="reference-json">
              {JSON.stringify(refData, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
