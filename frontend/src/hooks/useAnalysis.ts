"use client";
/**
 * HireLens — useAnalysis Hook
 * Fixed:
 * - Polling cleanup on unmount (memory leak fix)
 * - Error message extraction improved
 * - Network error handling
 * - Status check before setting complete
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { analysisAPI, reportsAPI, APIError } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import type { AnalysisJob, Report } from "@/types";

export type AnalysisState =
  | { phase: "idle" }
  | { phase: "uploading" }
  | { phase: "analyzing"; job: AnalysisJob }
  | { phase: "complete"; report: Report }
  | { phase: "error"; message: string };

export function useAnalysis() {
  const token = useAuthStore((s) => s.token);
  const [state, setState] = useState<AnalysisState>({ phase: "idle" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  // Cleanup on unmount — prevents memory leak and state updates on dead component
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const safeSetState = useCallback((s: AnalysisState) => {
    if (mountedRef.current) setState(s);
  }, []);

  const analyze = useCallback(
    async (file: File) => {
      if (!token) {
        safeSetState({ phase: "error", message: "Please log in to analyze resumes." });
        return;
      }

      safeSetState({ phase: "uploading" });
      stopPolling();

      try {
        // Step 1: Upload → get job_id
        const { job_id } = await analysisAPI.upload(file, token);

        let attempts = 0;
        const MAX_ATTEMPTS = 90; // 90 × 2s = 3 min max (Gemini can be slow)

        safeSetState({
          phase: "analyzing",
          job: {
            id: job_id,
            status: "queued",
            stage: "queued",
            progress: 0,
            file_name: file.name,
          },
        });

        // Step 2: Poll every 2 seconds
        pollRef.current = setInterval(async () => {
          if (!mountedRef.current) {
            stopPolling();
            return;
          }

          attempts++;

          if (attempts > MAX_ATTEMPTS) {
            stopPolling();
            safeSetState({
              phase: "error",
              message:
                "Analysis is taking longer than expected. Please try again. If the issue persists, the file may be too large or complex.",
            });
            return;
          }

          try {
            const job = await analysisAPI.status(job_id, token);

            if (!mountedRef.current) return;

            // Update progress display
            safeSetState({ phase: "analyzing", job });

            if (job.status === "complete" && job.report_id) {
              stopPolling();
              try {
                const report = await reportsAPI.get(job.report_id, token);
                // Add metadata to report
                const fullReport: Report = {
                  ...report,
                  id: job.report_id,
                  file_name: report.file_name || file.name,
                };
                safeSetState({ phase: "complete", report: fullReport });
              } catch (fetchErr) {
                safeSetState({
                  phase: "error",
                  message:
                    fetchErr instanceof APIError
                      ? `Analysis complete but report fetch failed: ${fetchErr.message}`
                      : "Analysis complete but could not load the report. Please check your dashboard.",
                });
              }
            } else if (job.status === "failed") {
              stopPolling();
              safeSetState({
                phase: "error",
                message:
                  job.error ||
                  "Analysis failed. Please try again with a different file.",
              });
            }
          } catch (pollErr) {
            if (pollErr instanceof APIError) {
              if (pollErr.status === 401) {
                stopPolling();
                safeSetState({
                  phase: "error",
                  message: "Your session expired. Please log in again.",
                });
              } else if (pollErr.status === 404) {
                stopPolling();
                safeSetState({
                  phase: "error",
                  message: "Analysis job not found. Please try uploading again.",
                });
              }
              // Other API errors: keep polling (transient network issues)
            }
            // Network errors: keep polling
          }
        }, 2000);
      } catch (uploadErr) {
        let message = "Upload failed. Please try again.";
        if (uploadErr instanceof APIError) {
          message = uploadErr.message;
        } else if (uploadErr instanceof TypeError && uploadErr.message.includes("fetch")) {
          message =
            "Cannot connect to the server. Please check your internet connection.";
        }
        safeSetState({ phase: "error", message });
      }
    },
    [token, stopPolling, safeSetState],
  );

  const reset = useCallback(() => {
    stopPolling();
    safeSetState({ phase: "idle" });
  }, [stopPolling, safeSetState]);

  return { state, analyze, reset };
}
