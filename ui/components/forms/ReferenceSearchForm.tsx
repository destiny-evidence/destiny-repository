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
      <button type="submit" disabled={loading}>
        {loading ? "Looking up..." : "Lookup Reference"}
      </button>
    </form>
  );
}
