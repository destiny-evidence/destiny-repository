// PageOverlay component for greying out the page with message/spinner

import React from "react";

interface PageOverlayProps {
  message?: string;
  showSpinner?: boolean;
}

export default function PageOverlay({
  message,
  showSpinner,
  fullPage = true,
}: PageOverlayProps & { fullPage?: boolean }) {
  return (
    <div
      style={{
        position: fullPage ? "fixed" : "absolute",
        zIndex: 9999,
        top: 0,
        left: 0,
        width: fullPage ? "100vw" : "100%",
        height: fullPage ? "100vh" : "100%",
        background: "rgba(240,240,240,0.7)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backdropFilter: "blur(2px)",
        pointerEvents: "auto",
      }}
      data-testid="page-overlay"
    >
      <div
        style={{
          color: "#888",
          fontWeight: "bold",
          fontSize: "1.2rem",
          background: "#fff",
          padding: "32px 48px",
          borderRadius: 12,
          boxShadow: "0 2px 16px rgba(0,0,0,0.08)",
          marginLeft: fullPage ? 0 : "16px",
          marginRight: fullPage ? 0 : "16px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 16,
        }}
      >
        {showSpinner && (
          <div className="spinner" style={{ marginBottom: 12 }} />
        )}
        {message}
      </div>
    </div>
  );
}
