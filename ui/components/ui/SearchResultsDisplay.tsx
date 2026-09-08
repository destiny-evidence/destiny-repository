// SearchResultsDisplay component for displaying paginated search results

import React from "react";
import BaseReferenceDisplay from "./BaseReferenceDisplay";
import {
  reachablePageCount,
  resolveMaxResultWindow,
} from "../../lib/api/searchPagination";

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
      max_result_window?: number;
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

  const maxResultWindow = resolveMaxResultWindow(
    results.page.max_result_window,
  );
  const totalPages = reachablePageCount(results.total.count, maxResultWindow);

  // Servers predating page.max_result_window cap the count rather than reporting
  // it, so this survives for rollbacks and mid-deploy transitions.
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
      {results.total.count > maxResultWindow && (
        <> Only the first {maxResultWindow.toLocaleString()} are retrievable.</>
      )}
    </div>
  );

  return (
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
  );
}
