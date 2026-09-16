"use client";

/**
 * Last-resort boundary, for a failure in the root layout itself.
 *
 * This replaces <html>, so it cannot rely on the app's layout, providers or
 * Tailwind's class layer being available — everything here is inline.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0A0C10",
          color: "#E8EBF0",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          padding: 20,
        }}
      >
        <div style={{ maxWidth: 420, textAlign: "center" }}>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>HireLens couldn&apos;t start</h1>
          <p style={{ marginTop: 10, fontSize: 14, lineHeight: 1.6, color: "#98A1B2" }}>
            Something went wrong loading the application. Your data is safe. Reloading usually
            fixes it.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: 22,
              height: 36,
              padding: "0 16px",
              borderRadius: 6,
              border: "none",
              background: "#5B63EF",
              color: "#fff",
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
          {error.digest && (
            <p style={{ marginTop: 22, fontSize: 11, color: "#646E80", fontFamily: "monospace" }}>
              Reference: {error.digest}
            </p>
          )}
        </div>
      </body>
    </html>
  );
}
