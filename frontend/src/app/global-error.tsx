"use client";

/**
 * Last-resort boundary for errors thrown by the root layout itself.
 *
 * `error.tsx` renders *inside* the root layout, so it cannot catch a failure
 * in the layout — for that case Next.js requires a global-error boundary that
 * supplies its own <html>/<body>. Deliberately plain inline styles with no
 * imports beyond React: if the layout blew up, anything it set up (fonts,
 * tokens, providers) may be exactly what is broken, so this file must not
 * depend on it.
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
          background: "#12141A",
          color: "#EDEDEA",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          padding: 24,
        }}
      >
        <div
          style={{
            maxWidth: 460,
            width: "100%",
            border: "1px solid #2A2D37",
            borderRadius: 8,
            background: "#191B22",
            padding: 32,
          }}
        >
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 12px" }}>
            HireLens could not load
          </h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "#B4B4AC", margin: "0 0 20px" }}>
            The application failed to start. Reloading usually clears it; if it
            keeps happening, the API may be unavailable.
          </p>
          {error.digest && (
            <div
              style={{
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: 12,
                color: "#8A8B82",
                marginBottom: 20,
                wordBreak: "break-all",
              }}
            >
              Reference: {error.digest}
            </div>
          )}
          <button
            onClick={() => reset()}
            style={{
              background: "#3B7D78",
              color: "#F5F5F2",
              border: "1px solid #3B7D78",
              borderRadius: 6,
              padding: "10px 18px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
