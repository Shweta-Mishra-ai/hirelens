"use client";

/**
 * Route-level error boundary.
 *
 * Without this file, any uncaught exception thrown while rendering a page
 * (a malformed API payload, a null deref in the 1,600-line report view)
 * unmounts the tree and leaves the user on Next.js's bare production
 * fallback: a blank page reading "Application error: a client-side
 * exception has occurred". No branding, no explanation, no way back, and
 * nothing in the UI that tells anyone what went wrong.
 *
 * This is the one file that turns that into a recoverable state — a real
 * message, a Try again button that re-renders the segment, and a route back
 * to the dashboard. `global-error.tsx` next to it covers the narrower case
 * of the root layout itself failing.
 */

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { color, font, radius } from "@/lib/design-tokens";
import { Button, Card, PageShell } from "@/components/ui/primitives";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Next strips the message from production errors client-side and gives
    // a `digest` that correlates with the server log entry. Surfacing it is
    // the only way a user can quote something actionable in a bug report.
    console.error("Unhandled route error:", error);
  }, [error]);

  return (
    <PageShell>
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
        }}
      >
        <Card style={{ maxWidth: 520, width: "100%", padding: 32 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <AlertTriangle size={20} color={color.danger} />
            <h1
              style={{
                fontFamily: font.display,
                fontSize: 22,
                fontWeight: 600,
                color: color.textPrimary,
                margin: 0,
              }}
            >
              Something went wrong
            </h1>
          </div>

          <p style={{ fontSize: 14, lineHeight: 1.6, color: color.textSecondary, margin: "0 0 20px" }}>
            This page hit an unexpected error. Your data has not been changed —
            retrying is safe.
          </p>

          {error.digest && (
            <div
              style={{
                fontFamily: font.mono,
                fontSize: 12,
                color: color.textMuted,
                background: color.bgAlt,
                border: `1px solid ${color.borderSubtle}`,
                borderRadius: radius.sm,
                padding: "8px 10px",
                marginBottom: 20,
                wordBreak: "break-all",
              }}
            >
              Reference: {error.digest}
            </div>
          )}

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Button onClick={() => reset()}>Try again</Button>
            <Link href="/dashboard" style={{ textDecoration: "none" }}>
              <Button variant="secondary">Back to dashboard</Button>
            </Link>
          </div>
        </Card>
      </div>
    </PageShell>
  );
}
