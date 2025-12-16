"use client";

import React, { useState } from "react";
import FormField from "./FormField";

interface SearchFormProps {
  onSearch: (query: string) => void;
  loading: boolean;
}

export default function SearchForm({ onSearch, loading }: SearchFormProps) {
  const [query, setQuery] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      onSearch(query.trim());
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <FormField
        label="Search query:"
        value={query}
        onChange={setQuery}
        required
      />
      <p
        style={{
          fontSize: "0.85rem",
          color: "#666",
          marginTop: 4,
          marginBottom: 16,
        }}
      >
        Searches title and abstract fields
      </p>
      <button type="submit" disabled={!query.trim() || loading}>
        {loading ? "Searching..." : "Search"}
      </button>
    </form>
  );
}
