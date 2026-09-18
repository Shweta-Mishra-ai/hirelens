"use client";
import { useEffect, useState } from "react";
import { healthAPI } from "@/lib/api";

export type Readiness =
  | { state: "checking" }
  | { state: "ready" }
  | { state: "no_provider" }
  | { state: "unreachable" };

/**
 * Asks the backend whether it can actually run an analysis.
 *
 * The upload endpoints now refuse when no AI provider is configured, but a
 * recruiter should not have to pick a file and press upload to discover that.
 * `/api/v1/health` already reports `llm_ready`; nothing consumed it.
 */
export function useAnalysisReadiness(): Readiness {
  const [readiness, setReadiness] = useState<Readiness>({ state: "checking" });

  useEffect(() => {
    let cancelled = false;
    healthAPI
      .check()
      .then((h) => {
        if (cancelled) return;
        setReadiness({ state: h.llm_ready ? "ready" : "no_provider" });
      })
      .catch(() => {
        if (!cancelled) setReadiness({ state: "unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return readiness;
}

/** Banner copy for a non-ready state, or null when uploads should work. */
export function readinessMessage(
  readiness: Readiness,
): { tone: "warning" | "error"; title: string; body: string } | null {
  if (readiness.state === "no_provider") {
    return {
      tone: "warning",
      title: "Resume analysis is unavailable",
      body:
        "No AI provider is configured on the server, so uploads cannot be processed right now. Your administrator needs to finish setting up HireLens. Nothing you upload will be lost — uploads are refused rather than queued.",
    };
  }
  if (readiness.state === "unreachable") {
    return {
      tone: "error",
      title: "Cannot reach the HireLens server",
      body:
        "The API is not responding. Check your connection, or try again in a moment.",
    };
  }
  return null;
}
