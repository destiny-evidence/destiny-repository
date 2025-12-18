// LookupResultsDisplay component for displaying reference lookup results

import React from "react";
import BaseReferenceDisplay from "./BaseReferenceDisplay";

interface LookupResultsDisplayProps {
  results: any[];
  searchedIdentifiers?: string[];
}

export default function LookupResultsDisplay({
  results,
  searchedIdentifiers = [],
}: LookupResultsDisplayProps) {
  const visualTabLabel = `Visual (${results.length} reference${
    results.length !== 1 ? "s" : ""
  })`;
  const downloadFilename = `references-bulk-${
    new Date().toISOString().split("T")[0]
  }.jsonl`;

  return (
    <BaseReferenceDisplay
      references={results}
      visualTabLabel={visualTabLabel}
      downloadFilename={downloadFilename}
      searchedIdentifiers={searchedIdentifiers}
      showSearchedIdentifiers={true}
      emptyStateTitle="No references loaded yet"
      emptyStateMessage="Please search for references to display their details."
    />
  );
}
