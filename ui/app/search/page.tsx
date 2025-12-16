"use client";

import { useState } from "react";
import SearchForm from "../../components/forms/SearchForm";
import SearchResults from "../../components/ui/SearchResults";
import Pagination from "../../components/ui/Pagination";
import ErrorDisplay from "../../components/ui/ErrorDisplay";
import LoadingSpinner from "../../components/ui/LoadingSpinner";
import PageOverlay from "../../components/ui/PageOverlay";
import { useApi } from "../../lib/api/useApi";
import { ReferenceSearchResult } from "../../lib/api/types";

const PAGE_SIZE = 20;

export default function SearchPage() {
  const [results, setResults] = useState<ReferenceSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [currentQuery, setCurrentQuery] = useState<string>("");
  const [currentPage, setCurrentPage] = useState(1);

  const { searchReferences, isLoggedIn, isLoginProcessing } = useApi();

  const handleSearch = async (query: string, page: number = 1) => {
    setError(null);
    setValidationError(null);
    setLoading(true);

    try {
      setCurrentQuery(query);
      setCurrentPage(page);
      const apiResult = await searchReferences(query, page);

      if (apiResult.error) {
        if (apiResult.error.type === "validation") {
          setValidationError(apiResult.error.detail);
        } else {
          setError(apiResult.error.detail);
        }
        setResults(null);
      } else if (apiResult.data) {
        setResults(apiResult.data);
      }
    } catch (err: any) {
      console.error(err);
      setError("Error performing search.");
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const handlePageChange = (page: number) => {
    if (currentQuery) {
      handleSearch(currentQuery, page);
    }
  };

  const totalPages = results ? Math.ceil(results.total.count / PAGE_SIZE) : 0;

  const showFormOverlay = !isLoggedIn && !isLoginProcessing;
  const showPageOverlay = isLoginProcessing;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "60vh",
        width: "100vw",
        marginLeft: "calc(-50vw + 50%)",
        background: "inherit",
        paddingLeft: 32,
        paddingRight: 32,
        position: "relative",
      }}
    >
      {showPageOverlay && (
        <PageOverlay message="Signing in..." showSpinner={true} />
      )}
      <h1
        style={{
          margin: "32px 0 24px 0",
          display: "block",
          width: "fit-content",
        }}
      >
        Search References
      </h1>
      <div
        style={{
          display: "flex",
          alignItems: "stretch",
          flex: 1,
        }}
      >
        <section
          style={{
            width: 340,
            minWidth: 260,
            padding: "32px",
            marginRight: 64,
            display: "flex",
            flexDirection: "column",
            gap: 16,
            alignItems: "flex-start",
            height: "100%",
            border: "1px solid #ddd",
            background: "#fff",
            boxSizing: "border-box",
            position: "relative",
          }}
        >
          {showFormOverlay && (
            <PageOverlay
              message="This feature requires sign-in."
              showSpinner={false}
              fullPage={false}
            />
          )}
          <SearchForm
            onSearch={(query) => handleSearch(query, 1)}
            loading={loading}
          />
        </section>
        <section
          style={{
            flex: 1,
            padding: "32px",
            minHeight: 340,
            display: "flex",
            flexDirection: "column",
            gap: 16,
            height: "100%",
            border: "1px solid #ddd",
            background: "#fff",
            boxSizing: "border-box",
          }}
        >
          {loading && <LoadingSpinner />}
          {validationError && (
            <ErrorDisplay error={validationError} type="validation" />
          )}
          {error && <ErrorDisplay error={error} type="generic" />}
          {results && !loading && (
            <>
              <SearchResults results={results} />
              {totalPages > 1 && (
                <Pagination
                  currentPage={currentPage}
                  totalPages={Math.min(totalPages, 500)}
                  onPageChange={handlePageChange}
                  loading={loading}
                />
              )}
            </>
          )}
          {!results && !loading && !error && !validationError && (
            <div
              style={{
                marginTop: 24,
                padding: "24px",
                background: "#f8f9fa",
                border: "1px solid #eee",
                borderRadius: "var(--border-radius)",
                color: "#555",
                textAlign: "center",
              }}
            >
              <h3>Search the repository</h3>
              <p>
                Enter a search query to find references by title or abstract.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
