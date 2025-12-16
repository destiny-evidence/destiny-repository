// SearchForm component for reference search using query strings

import React, { useState } from "react";
import FormField from "./FormField";

interface SearchFormProps {
  onSearch: (params: {
    query: string;
    page: number;
    startYear?: number;
    endYear?: number;
    annotations?: string[];
    sort?: string[];
  }) => void;
  loading: boolean;
  currentPage?: number;
  totalPages?: number;
}

export default function SearchForm({
  onSearch,
  loading,
  currentPage = 1,
  totalPages,
}: SearchFormProps) {
  const [query, setQuery] = useState("");
  const [startYear, setStartYear] = useState("");
  const [endYear, setEndYear] = useState("");
  const [annotationFilters, setAnnotationFilters] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    performSearch(1);
  };

  const performSearch = (page: number) => {
    const searchParams: any = {
      query,
      page,
    };

    if (startYear) searchParams.startYear = parseInt(startYear);
    if (endYear) searchParams.endYear = parseInt(endYear);
    if (annotationFilters.trim()) {
      searchParams.annotations = annotationFilters
        .split(/\r?\n/)
        .map((a) => a.trim())
        .filter((a) => a);
    }

    onSearch(searchParams);
  };

  const handlePreviousPage = () => {
    if (currentPage > 1) {
      performSearch(currentPage - 1);
    }
  };

  const handleNextPage = () => {
    if (!totalPages || currentPage < totalPages) {
      performSearch(currentPage + 1);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <div className="hint">
        At its simplest, this is a keyword search across the title and abstract.
        <br />
        <br />
        See the{" "}
        <a href="https://destiny-evidence.github.io/destiny-repository/procedures/search.html#query-string-required">
          documentation
        </a>{" "}
        for a list of fields and more advanced queries.
        <br />
        <br />
        Examples:
        <ul>
          <li>
            <code>pneumonia</code>
          </li>
          <li>
            <code>cats OR dogs</code>
          </li>
          <li>
            <code>
              title:"machine learning" AND inclusion_destiny:{">"}=0.8
            </code>
          </li>
          <li>
            <code>
              abstract:(/randomi[sz]ed/ AND "control trial") AND
              title:behavior~1 AND publication_year:2020
            </code>
          </li>
        </ul>
      </div>
      <div className="form-field">
        <label>Search Query:</label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          required
          rows={3}
          className="search-query-input"
          placeholder="Enter search query..."
        />
      </div>
      <button
        type="button"
        className="button-secondary"
        onClick={() => setShowFilters(!showFilters)}
      >
        {showFilters ? "Hide" : "Show"} Helper Filters
      </button>

      {showFilters && (
        <div>
          <div className="hint" style={{ marginBottom: 8 }}>
            These filters are applied to the above query to narrow down the
            search results. They might be helpful to avoid complex queries,
            particularly for annotations.
          </div>
          <div className="form-field">
            <div className="year-fields">
              <FormField
                label="Start Year:"
                value={startYear}
                onChange={setStartYear}
                type="number"
              />
              <FormField
                label="End Year:"
                value={endYear}
                onChange={setEndYear}
                type="number"
              />
            </div>
            <label>Annotation Filters (one per line):</label>
            <textarea
              value={annotationFilters}
              onChange={(e) => setAnnotationFilters(e.target.value)}
              rows={4}
              placeholder={`inclusion:destiny\nclassifier:taxonomy:Outcomes/Influenza`}
              disabled={loading}
            />
            <div className="hint">
              Format: <br />
              <code>&lt;scheme&gt;[/&lt;label&gt;][@&lt;score&gt;]</code>
              <br />
              See the{" "}
              <a href="https://destiny-evidence.github.io/destiny-repository/procedures/search.html#annotations">
                documentation
              </a>{" "}
              for more details.
            </div>
          </div>
        </div>
      )}
      <button type="submit" disabled={!query || loading}>
        {loading ? "Searching..." : "Search References"}
      </button>
      {totalPages != null && totalPages > 0 && (
        <div className="search-form-pagination">
          <button
            type="button"
            onClick={handlePreviousPage}
            disabled={loading || currentPage <= 1}
            className="button-secondary"
          >
            ← Prev
          </button>
          <span>
            Page {currentPage} of {totalPages}
          </span>
          <button
            type="button"
            onClick={handleNextPage}
            disabled={loading || currentPage >= totalPages}
            className="button-secondary"
          >
            Next →
          </button>
        </div>
      )}
    </form>
  );
}
