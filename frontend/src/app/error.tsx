"use client";
import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCcw, LayoutDashboard } from "lucide-react";

/**
 * Route-level error boundary.
 *
 * Next renders this in place of the page when a client render throws,
 * instead of the bare "Application error: a client-side exception has
 * occurred" that a recruiter cannot act on. `reset()` re-renders the route,
 * which recovers from anything transient without a full reload.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[HireLens] Route render failed", error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-5">
      <div className="w-full max-w-md text-center">
        <div
          aria-hidden
          className="mx-auto flex size-11 items-center justify-center rounded-xl border border-critical-line bg-critical-soft text-critical"
        >
          <AlertTriangle className="size-5" />
        </div>

        <h1 className="mt-5 text-xl font-semibold text-content">This page hit a problem</h1>
        <p className="mt-2 text-sm leading-relaxed text-content-muted">
          Something went wrong while displaying this page. Your data is safe — nothing was
          changed or lost. Trying again usually clears it.
        </p>

        <div className="mt-6 flex items-center justify-center gap-2.5">
          <button
            type="button"
            onClick={reset}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-brand-500 px-3.5 text-sm font-medium text-white transition-colors hover:bg-brand-400 focus-visible:outline-none focus-visible:shadow-focus"
          >
            <RotateCcw aria-hidden className="size-4" />
            Try again
          </button>
          <Link
            href="/dashboard"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-line-strong bg-canvas-overlay px-3.5 text-sm font-medium text-content transition-colors hover:bg-canvas-inset focus-visible:outline-none focus-visible:shadow-focus"
          >
            <LayoutDashboard aria-hidden className="size-4" />
            Back to dashboard
          </Link>
        </div>

        {error.digest && (
          <p className="mt-6 font-mono text-2xs text-content-faint">
            Reference: {error.digest}
          </p>
        )}
      </div>
    </div>
  );
}
