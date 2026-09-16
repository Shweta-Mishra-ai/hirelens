"use client";
/**
 * HireLens — useJdMatch Hook (Feature 2)
 * Handles: uploading a JD + many resumes, polling batch status until every
 * job reaches a terminal state, and exposing a live-updating JD-match ranking.
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { matchAPI, APIError, type JdInput } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import type { MatchBatchStatus, BulkUploadResponse } from "@/types";

export type MatchState =
  | { phase: "idle" }
  | { phase: "uploading" }
  | { phase: "processing"; batch: MatchBatchStatus }
  | { phase: "done"; batch: MatchBatchStatus }
  | { phase: "error"; message: string };

const POLL_MS = 2500;
const MAX_ATTEMPTS = 240;

export function useJdMatch() {
  const token = useAuthStore((s) => s.token);
  const [state, setState] = useState<MatchState>({ phase: "idle" });
  const [exporting, setExporting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const safeSetState = useCallback((s: MatchState) => {
    if (mountedRef.current) setState(s);
  }, []);

  const upload = useCallback(
    async (files: File[], jd: JdInput) => {
      if (!token) {
        safeSetState({ phase: "error", message: "Please log in to run a JD match." });
        return;
      }
      if (files.length === 0) {
        safeSetState({ phase: "error", message: "Select at least one PDF or DOCX resume." });
        return;
      }
      const hasText = !!jd.text && jd.text.trim().length >= 30;
      const hasFile = !!jd.file;
      if (!hasText && !hasFile) {
        safeSetState({
          phase: "error",
          message: "Paste a job description (at least a few sentences) or upload a JD file.",
        });
        return;
      }

      safeSetState({ phase: "uploading" });
      stopPolling();

      let uploadRes: BulkUploadResponse;
      try {
        uploadRes = await matchAPI.upload(files, jd, token);
      } catch (e) {
        const message =
          e instanceof APIError ? e.message : "Upload failed. Please try again.";
        safeSetState({ phase: "error", message });
        return;
      }

      const { batch_id } = uploadRes;
      let attempts = 0;
      // See useBulkAnalysis: the first poll runs before any interval exists,
      // so stopPolling() inside it is a no-op and the interval below would
      // start on an already-finished batch.
      let finished = false;
      const finish = () => {
        finished = true;
        stopPolling();
      };

      const pollOnce = async () => {
        if (!mountedRef.current) {
          finish();
          return;
        }
        attempts++;
        if (attempts > MAX_ATTEMPTS) {
          finish();
          safeSetState({
            phase: "error",
            message: "This batch is taking unusually long. Check your dashboard shortly.",
          });
          return;
        }

        try {
          const batch = await matchAPI.status(batch_id, token);
          if (!mountedRef.current) return;

          if (batch.is_done) {
            finish();
            safeSetState({ phase: "done", batch });
          } else {
            safeSetState({ phase: "processing", batch });
          }
        } catch (err) {
          if (err instanceof APIError && (err.status === 401 || err.status === 404)) {
            finish();
            safeSetState({
              phase: "error",
              message:
                err.status === 401
                  ? "Your session expired. Please log in again."
                  : "Batch not found. It may have expired.",
            });
          }
        }
      };

      await pollOnce();
      if (!finished && mountedRef.current) {
        pollRef.current = setInterval(pollOnce, POLL_MS);
      }
    },
    [token, stopPolling, safeSetState],
  );

  const exportCsv = useCallback(
    async (batchId: string) => {
      if (!token) return;
      setExporting(true);
      try {
        const blob = await matchAPI.downloadCsv(batchId, token);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `hirelens_jd_match_${batchId.slice(0, 8)}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch {
        // Non-fatal; caller can toast if desired.
      } finally {
        setExporting(false);
      }
    },
    [token],
  );

  const reset = useCallback(() => {
    stopPolling();
    safeSetState({ phase: "idle" });
  }, [stopPolling, safeSetState]);

  return { state, upload, exportCsv, exporting, reset };
}
