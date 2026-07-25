"use client";
/**
 * HireLens — useBulkAnalysis Hook (Feature 1)
 * Handles: uploading many files at once, polling batch status until every
 * job reaches a terminal state, and exposing a live-updating ranking.
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { bulkAPI, APIError } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import type { BatchStatus, BulkUploadResponse } from "@/types";

export type BulkState =
  | { phase: "idle" }
  | { phase: "uploading" }
  | { phase: "processing"; batch: BatchStatus }
  | { phase: "done"; batch: BatchStatus }
  | { phase: "error"; message: string };

const POLL_MS = 2500;
const MAX_ATTEMPTS = 240; // 240 × 2.5s = 10 min ceiling for large batches

export function useBulkAnalysis() {
  const token = useAuthStore((s) => s.token);
  const [state, setState] = useState<BulkState>({ phase: "idle" });
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

  const safeSetState = useCallback((s: BulkState) => {
    if (mountedRef.current) setState(s);
  }, []);

  const pollBatch = useCallback(
    (batchId: string) => {
      let attempts = 0;

      const pollOnce = async () => {
        if (!mountedRef.current || !token) {
          stopPolling();
          return;
        }
        attempts++;
        if (attempts > MAX_ATTEMPTS) {
          stopPolling();
          safeSetState({
            phase: "error",
            message: "This batch is taking unusually long. Check your dashboard shortly.",
          });
          return;
        }

        try {
          const batch = await bulkAPI.status(batchId, token);
          if (!mountedRef.current) return;

          if (batch.is_done) {
            stopPolling();
            safeSetState({ phase: "done", batch });
          } else {
            safeSetState({ phase: "processing", batch });
          }
        } catch (err) {
          if (err instanceof APIError && (err.status === 401 || err.status === 404)) {
            stopPolling();
            safeSetState({
              phase: "error",
              message:
                err.status === 401
                  ? "Your session expired. Please log in again."
                  : "Batch not found. It may have expired.",
            });
          }
          // Transient/network errors: keep polling silently.
        }
      };

      return pollOnce().then(() => {
        pollRef.current = setInterval(pollOnce, POLL_MS);
      });
    },
    [token, stopPolling, safeSetState],
  );

  const upload = useCallback(
    async (files: File[]) => {
      if (!token) {
        safeSetState({ phase: "error", message: "Please log in to upload resumes." });
        return;
      }
      if (files.length === 0) {
        safeSetState({ phase: "error", message: "Select at least one PDF or DOCX file." });
        return;
      }

      safeSetState({ phase: "uploading" });
      stopPolling();

      let uploadRes: BulkUploadResponse;
      try {
        uploadRes = await bulkAPI.upload(files, token);
      } catch (e) {
        const message =
          e instanceof APIError ? e.message : "Upload failed. Please try again.";
        safeSetState({ phase: "error", message });
        return;
      }

      await pollBatch(uploadRes.batch_id);
    },
    [token, stopPolling, safeSetState, pollBatch],
  );

  const uploadFromAts = useCallback(
    async (csvFile: File) => {
      if (!token) {
        safeSetState({ phase: "error", message: "Please log in to import candidates." });
        return;
      }

      safeSetState({ phase: "uploading" });
      stopPolling();

      let importRes: { batch_id: string; skipped_at_parse: { row_num: number; reason: string }[] };
      try {
        importRes = await bulkAPI.importFromAts(csvFile, token);
      } catch (e) {
        const message =
          e instanceof APIError ? e.message : "ATS import failed. Please check the CSV and try again.";
        safeSetState({ phase: "error", message });
        return;
      }

      await pollBatch(importRes.batch_id);
    },
    [token, stopPolling, safeSetState, pollBatch],
  );

  const exportCsv = useCallback(
    async (batchId: string) => {
      if (!token) return;
      setExporting(true);
      try {
        const blob = await bulkAPI.downloadCsv(batchId, token);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `hirelens_ranking_${batchId.slice(0, 8)}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch {
        // Surface via toast at the call site if desired; keep hook silent-safe.
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

  return { state, upload, uploadFromAts, exportCsv, exporting, reset };
}
