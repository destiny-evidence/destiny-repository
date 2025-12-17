// Reference Lookup page moved to /references

"use client";

import { useState } from "react";
import ReferenceLookupForm from "../../components/forms/ReferenceLookupForm";
import MultiReferenceLookupForm from "../../components/forms/MultiReferenceLookupForm";
import SearchForm from "../../components/forms/SearchForm";
import ErrorDisplay from "../../components/ui/ErrorDisplay";
import LoadingSpinner from "../../components/ui/LoadingSpinner";
import PageOverlay from "../../components/ui/PageOverlay";
import { useApi } from "../../lib/api/useApi";
import { ReferenceLookupParams, SearchParams } from "../../lib/api/types";
import LookupResultsDisplay from "@/components/ui/LookupResultsDisplay";
import SearchResultsDisplay from "@/components/ui/SearchResultsDisplay";
import { toIdentifierString } from "../../lib/api/identifierUtils";

export default function ReferenceLookupPage() {
  const [activeTab, setActiveTab] = useState<"lookup" | "search">("lookup");
  const [result, setResult] = useState<Array<any> | null>(null);
  const [searchResult, setSearchResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [bulkIdentifiers, setBulkIdentifiers] = useState<string[]>([]);
  const [lookedUpIdentifiers, setLookedUpIdentifiers] = useState<string[]>([]);
  const [currentSearchParams, setCurrentSearchParams] =
    useState<SearchParams | null>(null);

  const { fetchReferences, searchReferences, isLoggedIn, isLoginProcessing } =
    useApi();

  // Detect login processing state is now handled by useApi

  const handleLookup = async (params: ReferenceLookupParams) => {
    setError(null);
    setValidationError(null);
    setResult(null);

    setLoading(true);

    try {
      const identifierString = toIdentifierString(params);
      setLookedUpIdentifiers([identifierString]);
      const apiResult = await fetchReferences([identifierString]);

      if (apiResult.error) {
        if (apiResult.error.type === "validation") {
          setValidationError(apiResult.error.detail);
        } else {
          setError(apiResult.error.detail);
        }
      } else {
        setResult(apiResult.data);
      }
    } catch (err: any) {
      console.error(err);
      setError("Error fetching reference.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddToBulk = (identifierString: string) => {
    setBulkIdentifiers((prev) => [...prev, identifierString]);
  };

  const handleBulkLookup = async (identifiers: string[]) => {
    setError(null);
    setValidationError(null);
    setResult(null);

    setLoading(true);

    try {
      setLookedUpIdentifiers(identifiers);
      const apiResult = await fetchReferences(identifiers);

      if (apiResult.error) {
        if (apiResult.error.type === "validation") {
          setValidationError(apiResult.error.detail);
        } else {
          setError(apiResult.error.detail);
        }
      } else {
        setResult(apiResult.data);
      }
    } catch (err: any) {
      console.error(err);
      setError("Error fetching references.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async (params: SearchParams) => {
    setError(null);
    setValidationError(null);
    setSearchResult(null);
    setCurrentSearchParams(params);

    setLoading(true);

    try {
      const apiResult = await searchReferences(params);

      if (apiResult.error) {
        if (apiResult.error.type === "validation") {
          setValidationError(apiResult.error.detail);
        } else {
          setError(apiResult.error.detail);
        }
      } else {
        setSearchResult(apiResult.data);
      }
    } catch (err: any) {
      console.error(err);
      setError("Error searching references.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearchPageChange = (page: number) => {
    if (currentSearchParams) {
      handleSearch({ ...currentSearchParams, page });
    }
  };

  // Overlay logic
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
        References
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

          {/* Tab switcher */}
          <div
            className="tab-group"
            style={{ width: "100%", marginBottom: 16 }}
          >
            <button
              className={`tab ${activeTab === "lookup" ? "active" : ""}`}
              onClick={() => setActiveTab("lookup")}
              style={{ flex: 1 }}
            >
              Lookup
            </button>
            <button
              className={`tab ${activeTab === "search" ? "active" : ""}`}
              onClick={() => setActiveTab("search")}
              style={{ flex: 1 }}
            >
              Search
            </button>
          </div>

          {/* Lookup Tab Content */}
          {activeTab === "lookup" && (
            <>
              <ReferenceLookupForm
                onSearch={handleLookup}
                onAddToBulk={handleAddToBulk}
                loading={loading}
              />
              <MultiReferenceLookupForm
                onSearch={handleBulkLookup}
                loading={loading}
                externalIdentifiers={bulkIdentifiers}
              />
            </>
          )}

          {/* Search Tab Content */}
          {activeTab === "search" && (
            <SearchForm
              onSearch={handleSearch}
              loading={loading}
              currentPage={searchResult?.page.number}
              totalPages={
                searchResult
                  ? Math.ceil(
                      searchResult.total.count / searchResult.page.count,
                    )
                  : undefined
              }
            />
          )}
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
            border: "1px solid #a97c7cff",
            background: "#fff",
            boxSizing: "border-box",
          }}
        >
          {loading && <LoadingSpinner />}
          {validationError && (
            <ErrorDisplay error={validationError} type="validation" />
          )}
          {error && <ErrorDisplay error={error} type="generic" />}
          {activeTab === "lookup" && result && (
            <LookupResultsDisplay
              results={result}
              searchedIdentifiers={lookedUpIdentifiers}
            />
          )}
          {activeTab === "search" && searchResult && (
            <SearchResultsDisplay
              results={searchResult}
              onPageChange={handleSearchPageChange}
            />
          )}
        </section>
      </div>
    </div>
  );
}
