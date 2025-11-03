// MultiReferenceSearchForm component for bulk reference lookup

import React, { useState, useEffect } from "react";

interface MultiReferenceSearchFormProps {
  onSearch: (identifiers: string[]) => void;
  loading: boolean;
  externalIdentifiers?: string[];
}

export default function MultiReferenceSearchForm({
  onSearch,
  loading,
  externalIdentifiers = [],
}: MultiReferenceSearchFormProps) {
  const [bulkInput, setBulkInput] = useState("");
  const [identifierCount, setIdentifierCount] = useState(0);

  // Add external identifiers to the input
  useEffect(() => {
    if (externalIdentifiers.length > 0) {
      const newIdentifier = externalIdentifiers[externalIdentifiers.length - 1];
      setBulkInput((prev) => {
        const existing = prev.trim();
        return existing ? `${existing}\n${newIdentifier}` : newIdentifier;
      });
    }
  }, [externalIdentifiers]);

  // Count identifiers on input change
  useEffect(() => {
    const lines = bulkInput
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    setIdentifierCount(lines.length);
  }, [bulkInput]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const identifiers = bulkInput
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    if (identifiers.length > 0) {
      onSearch(identifiers);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="multi-reference-search-form">
      <div className="form-section-divider">
        <span>Bulk Lookup</span>
      </div>
      <label htmlFor="bulk-ref-lookup" className="bulk-label">
        Enter identifiers (one per line):
      </label>
      <textarea
        // The word "identifier" or "id" is a password manager auto-complete trigger
        // Renaming the id and name to avoid that behavior
        id="bulk-ref-lookup"
        name="bulk-ref-lookup"
        value={bulkInput}
        onChange={(e) => setBulkInput(e.target.value)}
        className="bulk-textarea"
        rows={8}
        placeholder={`doi:10.1234/abcd\npm_id:123456\nopen_alex:W1234567\nother:isbn:978-1-234-56789-0\n02e376ee-8374-4a8c-997f-9a813bc5b8f8`}
        disabled={loading}
      />
      <div className="bulk-hint">
        Format: <code>type:identifier</code> or{" "}
        <code>other:type:identifier</code> or UUID for Destiny ID
      </div>
      <div className="bulk-identifier-count">
        {identifierCount} identifier{identifierCount !== 1 ? "s" : ""}
      </div>
      <button
        type="submit"
        disabled={loading || identifierCount === 0}
        className="bulk-submit-btn"
      >
        {loading
          ? "Looking up..."
          : `Lookup ${identifierCount} Reference${
              identifierCount !== 1 ? "s" : ""
            }`}
      </button>
    </form>
  );
}
