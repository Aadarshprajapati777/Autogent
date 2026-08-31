"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html>
      <body style={{ margin: 0, background: "#09090b", color: "#f5f4f8", fontFamily: "system-ui, sans-serif" }}>
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "2rem",
            textAlign: "center",
          }}
        >
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: 16,
              background: "rgba(255,107,107,0.1)",
              display: "grid",
              placeItems: "center",
              fontSize: 32,
            }}
          >
            ⚠️
          </div>
          <h1 style={{ fontSize: 30, fontWeight: 700, marginTop: 24 }}>
            Application error
          </h1>
          <p style={{ color: "#71717a", marginTop: 8, maxWidth: 400 }}>
            A critical error occurred. Please try reloading the page. If the problem persists,
            contact support.
          </p>
          {error.digest && (
            <p
              style={{
                marginTop: 12,
                fontFamily: "monospace",
                fontSize: 12,
                color: "#52525b",
                background: "#121216",
                border: "1px solid #28282e",
                borderRadius: 6,
                padding: "6px 12px",
              }}
            >
              ID: {error.digest}
            </p>
          )}
          <button
            onClick={reset}
            style={{
              marginTop: 24,
              background: "#75e0bd",
              color: "#09090b",
              border: "none",
              borderRadius: 8,
              padding: "10px 20px",
              fontWeight: 600,
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
