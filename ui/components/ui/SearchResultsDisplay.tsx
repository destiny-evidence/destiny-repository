// SearchResultsDisplay component for displaying paginated search results

import React from "react";
import BaseReferenceDisplay from "./BaseReferenceDisplay";

interface SearchResultsDisplayProps {
  results?: {
    references: any[];
    total: {
      count: number;
      is_lower_bound: boolean;
    };
    page: {
      count: number;
      number: number;
    };
  };
  onPageChange?: (page: number) => void;
}

export default function SearchResultsDisplay({
  results,
  onPageChange,
}: SearchResultsDisplayProps) {
  if (!results || results.references.length === 0) {
    return (
      <div className="empty-state">
        <h3>No results found</h3>
        <p>Try adjusting your search query or filters.</p>
      </div>
    );
  }

  // Calculate pagination info
  const pageSize = results.page.count;
  const totalPages = Math.ceil(results.total.count / pageSize);
  const displayTotal = results.total.is_lower_bound
    ? `>${results.total.count.toLocaleString()}`
    : results.total.count.toLocaleString();

  const visualTabLabel = `Visual`;
  const downloadFilename = `search-results-${
    new Date().toISOString().split("T")[0]
  }.jsonl`;

  // Header content with pagination info
  const headerContent = (
    <div className="pagination-info">
      <strong>Page {results.page.number}</strong> of {totalPages} (Total:{" "}
      {displayTotal} results, showing {results.references.length} per page)
    </div>
  );

  // Footer content with pagination controls
  const footerContent = onPageChange && totalPages > 1 && (
    <div className="pagination-controls">
      <button
        type="button"
        onClick={() => onPageChange(results.page.number - 1)}
        disabled={results.page.number <= 1}
        className="button-secondary"
      >
        ← Previous
      </button>
      <span>
        Page {results.page.number} of {totalPages}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(results.page.number + 1)}
        disabled={results.page.number >= totalPages}
        className="button-secondary"
      >
        Next →
      </button>
    </div>
  );

  return (
    <>
      <BaseReferenceDisplay
        references={results.references}
        visualTabLabel={visualTabLabel}
        downloadFilename={downloadFilename}
        headerContent={headerContent}
        jsonData={results.references}
        showSearchedIdentifiers={false}
        emptyStateTitle="No results found"
        emptyStateMessage="Try adjusting your search query or filters."
      />
      {footerContent}
    </>
  );
}
