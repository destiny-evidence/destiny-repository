// Reference Lookup page moved to /references

"use client";

import React, { useState } from "react";
import ReferenceSearchForm from "../../components/forms/ReferenceSearchForm";
import ErrorDisplay from "../../components/ui/ErrorDisplay";
import ReferenceDisplay from "../../components/ui/ReferenceDisplay";
import LoadingSpinner from "../../components/ui/LoadingSpinner";
import PageOverlay from "../../components/ui/PageOverlay";
import { useApi } from "../../lib/api/useApi";
import { ReferenceLookupParams } from "../../lib/api/types";
import { InteractionStatus } from "@azure/msal-browser";

export default function ReferenceLookupPage() {
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const { fetchReference, isLoggedIn, isLoginProcessing } = useApi();

  // Detect login processing state is now handled by useApi

  const handleSearch = async (params: ReferenceLookupParams) => {
    setError(null);
    setValidationError(null);
    setResult(null);

    setLoading(true);

    try {
      const apiResult = await fetchReference(params);

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
      setError("Error fetching reference.");
    } finally {
      setLoading(false);
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
        Reference Lookup
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
          <ReferenceSearchForm
            onSearch={handleSearch}
            loading={loading}
            isLoggedIn={isLoggedIn}
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
          <ErrorDisplay error={validationError} type="validation" />
          <ErrorDisplay error={error} type="generic" />
          <ReferenceDisplay result={result} />
        </section>
      </div>
    </div>
  );
}
