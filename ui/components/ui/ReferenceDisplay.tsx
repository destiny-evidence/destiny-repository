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

const MOCK_REFERENCE = {
  id: "123e4567-e89b-12d3-a456-426614174000",
  visibility: "PUBLIC",
  identifiers: [
    {
      identifier_type: "doi",
      identifier: "10.1000/xyz123",
    },
    {
      identifier_type: "pm_id",
      identifier: 9876543,
    },
    {
      identifier_type: "open_alex",
      identifier: "W123456789",
    },
    {
      identifier_type: "other",
      identifier: "ABC-123",
      other_identifier_name: "CustomID",
    },
  ],
  enhancements: [
    {
      id: "enh-1",
      reference_id: "123e4567-e89b-12d3-a456-426614174000",
      source: "OpenAlex",
      visibility: "PUBLIC",
      robot_version: "1.0.0",
      content: {
        enhancement_type: "BIBLIOGRAPHIC",
        authorship: [
          {
            display_name: "Jane Doe",
            orcid: "0000-0002-1825-0097",
            position: "FIRST",
          },
          {
            display_name: "John Smith",
            orcid: null,
            position: "LAST",
          },
        ],
        cited_by_count: 42,
        created_date: "2024-01-01",
        publication_date: "2023-12-15",
        publication_year: 2023,
        publisher: "Science Press",
        title: "A Comprehensive Study of Destiny",
      },
    },
    {
      id: "enh-2",
      reference_id: "123e4567-e89b-12d3-a456-426614174000",
      source: "Elsevier",
      visibility: "RESTRICTED",
      robot_version: "2.1.0",
      content: {
        enhancement_type: "ABSTRACT",
        process: "UNINVERTED",
        abstract:
          "This paper explores the intricacies of the Destiny repository and its impact on scientific data management.",
      },
    },
    {
      id: "enh-3",
      reference_id: "123e4567-e89b-12d3-a456-426614174000",
      source: "TagBot",
      visibility: "PUBLIC",
      robot_version: "0.9.1",
      content: {
        enhancement_type: "ANNOTATION",
        annotations: [
          {
            annotation_type: "BOOLEAN",
            scheme: "openalex:topic",
            label: "Data Science",
            value: true,
            score: 0.98,
            data: {},
          },
          {
            annotation_type: "SCORE",
            scheme: "pubmed:mesh",
            label: "Repository",
            score: 0.85,
            data: {},
          },
        ],
      },
    },
    {
      id: "enh-4",
      reference_id: "123e4567-e89b-12d3-a456-426614174000",
      source: "LocationBot",
      visibility: "PUBLIC",
      robot_version: "1.2.3",
      content: {
        enhancement_type: "LOCATION",
        locations: [
          {
            is_oa: true,
            version: "publishedVersion",
            landing_page_url: "https://example.com/article",
            pdf_url: "https://example.com/article.pdf",
            license: "cc-by",
            extra: { note: "Open access" },
          },
        ],
      },
    },
  ],
};

export default function ReferenceDisplay({ result }: ReferenceDisplayProps) {
  const [tab, setTab] = useState<"visual" | "json">("visual");
  // Use mock if no result provided
  const refData = result || MOCK_REFERENCE;

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
            <pre>{JSON.stringify(refData, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
