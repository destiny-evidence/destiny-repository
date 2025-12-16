"use client";

import React from "react";

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  loading?: boolean;
}

export default function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  loading = false,
}: PaginationProps) {
  const canGoPrev = currentPage > 1;
  const canGoNext = currentPage < totalPages;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        marginTop: 16,
      }}
    >
      <button
        className="button-secondary"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={!canGoPrev || loading}
        style={{ minWidth: 80 }}
      >
        Previous
      </button>
      <span style={{ fontSize: "0.9rem", color: "#666" }}>
        Page {currentPage} of {totalPages}
      </span>
      <button
        className="button-secondary"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={!canGoNext || loading}
        style={{ minWidth: 80 }}
      >
        Next
      </button>
    </div>
  );
}
