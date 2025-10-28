// ReferenceSearchForm component for reference lookup (refactored for lifted state)

import React, { useState } from "react";
import FormField from "./FormField";
import IdentifierTypeSelect from "./IdentifierTypeSelect";

interface ReferenceSearchFormProps {
  onSearch: (params: {
    identifier: string;
    identifierType: string;
    otherIdentifierName?: string;
  }) => void;
  loading: boolean;
  isLoggedIn: boolean;
}

export default function ReferenceSearchForm({
  onSearch,
  loading,
  isLoggedIn,
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

  return (
    <div style={{ position: "relative" }}>
      {!isLoggedIn && (
        <div
          style={{
            position: "absolute",
            zIndex: 2,
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(240,240,240,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#888",
            fontWeight: "bold",
            fontSize: "1.1rem",
            borderRadius: 8,
          }}
        >
          Must be logged in to use this
        </div>
      )}
      <form
        onSubmit={handleSubmit}
        style={{
          opacity: isLoggedIn ? 1 : 0.5,
          pointerEvents: isLoggedIn ? "auto" : "none",
        }}
      >
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
        <button type="submit" disabled={loading || !isLoggedIn}>
          {loading ? "Looking up..." : "Lookup Reference"}
        </button>
      </form>
    </div>
  );
}
