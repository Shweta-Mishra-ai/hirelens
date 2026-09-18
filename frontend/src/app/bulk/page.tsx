"use client";
import { useCallback, useState } from "react";
import Link from "next/link";
import {
  X,
  Download,
  CheckCircle2,
  CopyCheck,
  Layers,
  Play,
  RotateCcw,
  ArrowRight,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { useBulkAnalysis } from "@/hooks/useBulkAnalysis";
import { bulkAPI, APIError } from "@/lib/api";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { FileDropzone, type FileRejection } from "@/components/FileDropzone";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState } from "@/components/ui/Feedback";
import { ScorePill } from "@/components/ui/Score";
import { formatBytes, pluralize } from "@/lib/format";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import type { DuplicateCheckResult } from "@/types";

const MAX_FILES = 50;

function BulkContent() {
  const token = useAuthStore((s) => s.token);
  const { state, upload, exportCsv, exporting, exportError, reset } = useBulkAnalysis();

  const [pending, setPending] = useState<File[]>([]);
  const [rejections, setRejections] = useState<FileRejection[]>([]);
  const [dupResult, setDupResult] = useState<DuplicateCheckResult | null>(null);
  const [dupLoading, setDupLoading] = useState(false);
  const [dupError, setDupError] = useState<string | null>(null);

  const addFiles = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      setPending((prev) => {
        // De-duplicate by name+size so dropping the same folder twice doesn't
        // queue everything again.
        const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
        const fresh = accepted.filter((f) => !seen.has(`${f.name}:${f.size}`));
        const combined = [...prev, ...fresh];
        if (combined.length > MAX_FILES) {
          setRejections([
            ...rejected,
            ...combined.slice(MAX_FILES).map((f) => ({
              file: f,
              reason: `Batch limit is ${MAX_FILES} files.`,
            })),
          ]);
          return combined.slice(0, MAX_FILES);
        }
        setRejections(rejected);
        return combined;
      });
    },
    [],
  );

  async function checkDuplicates(batchId: string) {
    if (!token) return;
    setDupLoading(true);
    setDupError(null);
    try {
      setDupResult(await bulkAPI.checkDuplicates(batchId, token));
    } catch (e) {
      setDupError(e instanceof APIError ? e.message : "Could not run the duplicate check.");
    } finally {
      setDupLoading(false);
    }
  }

  function startOver() {
    reset();
    setPending([]);
    setRejections([]);
    setDupResult(null);
    setDupError(null);
  }

  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;
  const totalBytes = pending.reduce((n, f) => n + f.size, 0);
  const pct = batch && batch.total ? Math.round((batch.complete / batch.total) * 100) : 0;

  return (
    <AppShell>
      <PageHeader
        title="Bulk upload"
        description={`Analyse up to ${MAX_FILES} resumes in one batch. Candidates are ranked by credibility, and you can scan the batch for duplicate or templated resumes.`}
        actions={
          batch && state.phase === "done" ? (
            <Button icon={<RotateCcw className="size-4" />} onClick={startOver}>
              New batch
            </Button>
          ) : null
        }
      />

      {state.phase === "error" && (
        <Alert tone="error" title="Batch failed" className="mb-5">
          <p>{state.message}</p>
          <Button size="sm" className="mt-3" onClick={startOver}>
            Start over
          </Button>
        </Alert>
      )}

      {rejections.length > 0 && (
        <Alert tone="warning" className="mb-5" onDismiss={() => setRejections([])}>
          <p className="mb-1 font-medium">
            {pluralize(rejections.length, "file")} skipped
          </p>
          <ul className="space-y-0.5">
            {rejections.slice(0, 5).map((r, i) => (
              <li key={i}>
                <span className="font-mono text-xs">{r.file.name}</span> — {r.reason}
              </li>
            ))}
            {rejections.length > 5 && <li>…and {rejections.length - 5} more.</li>}
          </ul>
        </Alert>
      )}

      {state.phase === "idle" && (
        <div className="space-y-5">
          <FileDropzone
            onFiles={addFiles}
            multiple
            maxFiles={MAX_FILES}
            title="Drop candidate resumes here"
            hint={`PDF or DOCX · up to ${MAX_FILES} files · 10MB each`}
          />

          {pending.length > 0 && (
            <Card>
              <CardHeader
                title={`${pluralize(pending.length, "file")} queued`}
                description={`${formatBytes(totalBytes)} total · ${MAX_FILES - pending.length} slots remaining`}
                action={
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => setPending([])}>
                      Clear
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<Play className="size-3.5" />}
                      onClick={() => upload(pending)}
                    >
                      Analyse batch
                    </Button>
                  </div>
                }
              />
              <CardBody className="p-3">
                <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {pending.map((f, i) => (
                    <li
                      key={`${f.name}:${f.size}:${i}`}
                      className="flex items-center gap-2 rounded-md border border-line-subtle bg-canvas-inset px-2.5 py-1.5"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono text-xs text-content-muted">
                        {f.name}
                      </span>
                      <span className="shrink-0 text-2xs tabular text-content-faint">
                        {formatBytes(f.size)}
                      </span>
                      <button
                        type="button"
                        aria-label={`Remove ${f.name}`}
                        onClick={() => setPending((p) => p.filter((_, idx) => idx !== i))}
                        className="-mr-1 shrink-0 rounded p-1 text-content-faint transition-colors hover:text-critical"
                      >
                        <X className="size-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}
        </div>
      )}

      {batch && (
        <div className="space-y-5">
          <Card>
            <CardBody>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h2 className="text-sm font-semibold text-content">
                    {state.phase === "done" ? "Batch complete" : "Analysing batch"}
                  </h2>
                  <p className="mt-0.5 text-xs text-content-faint">
                    {batch.complete} of {batch.total} analysed
                    {batch.failed ? ` · ${batch.failed} failed` : ""}
                  </p>
                </div>
                {state.phase === "done" && (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      icon={<CopyCheck className="size-3.5" />}
                      loading={dupLoading}
                      onClick={() => checkDuplicates(batch.batch_id)}
                    >
                      Scan for duplicates
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<Download className="size-3.5" />}
                      loading={exporting}
                      onClick={() => exportCsv(batch.batch_id)}
                    >
                      Export CSV
                    </Button>
                  </div>
                )}
              </div>

              <div
                className="mt-4 h-1 overflow-hidden rounded-full bg-canvas-inset"
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Batch progress"
              >
                <div
                  className="h-full rounded-full bg-brand-500 transition-[width] duration-500 ease-out"
                  style={{ width: `${Math.max(pct, 2)}%` }}
                />
              </div>

              {exportError && (
                <p className="mt-3 text-xs text-critical">{exportError}</p>
              )}
            </CardBody>
          </Card>

          {dupError && <Alert tone="error">{dupError}</Alert>}

          {dupResult &&
            (dupResult.clusters.length === 0 ? (
              <Alert tone="success" title="No duplicates found">
                No two resumes in this batch shared enough wording to suggest a shared
                template or a re-submission.
              </Alert>
            ) : (
              <Card>
                <CardHeader
                  title="Possible duplicate submissions"
                  description="These resumes share substantial wording. That can mean a re-submission under two names, a shared template, or a resume-writing service — check the originals before drawing a conclusion."
                />
                <CardBody className="space-y-2.5">
                  {/*
                    The API returns `members: [{id, name}]` and a `similarity`
                    ratio. An earlier version of this view read `c.candidates`
                    and `x.candidate_name` — neither of which exists on the
                    response — behind an `any` cast, so the moment a batch
                    actually contained a duplicate this panel threw on
                    `undefined.length` and took the page down with it.
                  */}
                  {dupResult.clusters.map((c, i) => (
                    <div
                      key={i}
                      className="rounded-lg border border-caution-line bg-caution-soft px-3.5 py-2.5"
                    >
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-xs font-medium uppercase tracking-wide text-caution">
                          Group {i + 1} · {pluralize(c.members.length, "resume")}
                        </span>
                        <span className="text-xs tabular text-content-faint">
                          {Math.round(c.similarity * 100)}% text overlap
                        </span>
                      </div>
                      <div className="mt-1 text-sm text-content">
                        {c.members.map((m) => m.name || "Unknown").join(" · ")}
                      </div>
                    </div>
                  ))}
                </CardBody>
              </Card>
            ))}

          <Card className="overflow-hidden">
            <CardHeader
              title="Ranked by credibility"
              action={
                <span className="text-xs text-content-faint">
                  {pluralize(batch.ranking.length, "candidate")}
                </span>
              }
            />
            {batch.ranking.length === 0 ? (
              <EmptyState
                icon={<Layers className="size-5" />}
                title="No results yet"
                description="Candidates appear here as each resume finishes analysing."
              />
            ) : (
              <ErrorBoundary title="The ranking" resetKeys={[batch.batch_id]}>
              <div className="divide-y divide-line-subtle">
                {batch.ranking.map((c, i) => (
                  <div key={c.report_id || i} className="flex items-center gap-4 px-5 py-3.5">
                    <span className="w-6 shrink-0 text-sm tabular text-content-faint">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-content">
                        {c.candidate_name || "Unknown candidate"}
                      </div>
                      <div className="truncate font-mono text-xs text-content-faint">
                        {c.file_name}
                      </div>
                    </div>
                    <ScorePill score={c.overall_score} />
                    <span className="hidden sm:block">
                      <VerdictChip verdict={verdictFromRecommendation(c.recommendation)} />
                    </span>
                    <Link
                      href={`/report/${c.report_id}`}
                      className="shrink-0 text-xs font-medium text-brand-400 underline-offset-4 hover:underline"
                    >
                      <span className="flex items-center gap-1">
                        Open
                        <ArrowRight aria-hidden className="size-3.5" />
                      </span>
                    </Link>
                  </div>
                ))}
              </div>
              </ErrorBoundary>
            )}
          </Card>
        </div>
      )}

      {state.phase === "uploading" && !batch && (
        <Card>
          <EmptyState
            icon={<Layers className="size-5" />}
            title="Uploading your batch…"
            description="Large batches can take a moment to transfer before analysis begins."
          />
        </Card>
      )}
    </AppShell>
  );
}

export default function BulkPage() {
  return (
    <RequireAuth>
      <BulkContent />
    </RequireAuth>
  );
}
