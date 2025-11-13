// ReferenceSearchForm component for reference lookup (refactored for lifted state)

import React, { useState } from "react";
import FormField from "./FormField";
import IdentifierTypeSelect from "./IdentifierTypeSelect";
import { toIdentifierString } from "../../lib/api/identifierUtils";

interface ReferenceSearchFormProps {
  onSearch: (params: {
    identifier: string;
    identifierType: string;
    otherIdentifierName?: string;
  }) => void;
  onAddToBulk?: (identifierString: string) => void;
  loading: boolean;
}

export default function ReferenceSearchForm({
  onSearch,
  onAddToBulk,
  loading,
}: ReferenceSearchFormProps) {
  const [identifier, setIdentifier] = useState("");
  const [identifierType, setIdentifierType] = useState("doi");
  const [otherIdentifierName, setOtherIdentifierName] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch({
      identifier,
      identifierType,
      otherIdentifierName:
        identifierType === "other" ? otherIdentifierName : undefined,
    });
  };

  const handleAddToBulk = () => {
    if (onAddToBulk && identifier) {
      const identifierString = toIdentifierString({
        identifier,
        identifierType,
        otherIdentifierName:
          identifierType === "other" ? otherIdentifierName : undefined,
      });
      onAddToBulk(identifierString);
      // Clear form after adding
      setIdentifier("");
      setOtherIdentifierName("");
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <FormField
        label="Identifier:"
        value={identifier}
        onChange={setIdentifier}
        required
      />
      <IdentifierTypeSelect
        value={identifierType}
        onChange={setIdentifierType}
      />
      {identifierType === "other" && (
        <FormField
          label="Other Identifier Name:"
          value={otherIdentifierName}
          onChange={setOtherIdentifierName}
          required
        />
      )}
      <div style={{ display: "flex", gap: "8px" }}>
        {onAddToBulk && (
          <button
            type="button"
            className="button-secondary"
            onClick={handleAddToBulk}
            disabled={!identifier || loading}
          >
            Add to Bulk
          </button>
        )}
        <button type="submit" disabled={!identifier || loading}>
          {loading ? "Looking up..." : "Lookup Reference"}
        </button>
      </div>
    </form>
  );
}
