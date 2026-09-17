"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  X,
  Download,
  Crosshair,
  Play,
  RotateCcw,
  ChevronDown,
  Check,
  Minus,
  Trophy,
  Trash2,
} from "lucide-react";
import { useJdMatch } from "@/hooks/useJdMatch";
import { useAuthStore } from "@/store/auth";
import { jdsAPI, APIError, type SavedJd } from "@/lib/api";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { FileDropzone, type FileRejection } from "@/components/FileDropzone";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input, Textarea } from "@/components/ui/Field";
import { Alert, EmptyState } from "@/components/ui/Feedback";
import { ScorePill } from "@/components/ui/Score";
import { cn } from "@/lib/cn";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { formatBytes, pluralize } from "@/lib/format";
import type { MatchVerdict, MatchedCandidate } from "@/types";

const MAX_FILES = 50;
const JD_MIN_CHARS = 30;
const JD_ACCEPT = [".pdf", ".docx", ".txt"];
const JD_MAX_MB = 5;

const VERDICT_TONE: Record<MatchVerdict, "positive" | "caution" | "critical" | "neutral"> = {
  strong_fit: "positive",
  partial_fit: "caution",
  weak_fit: "critical",
  unknown: "neutral",
};

const VERDICT_LABEL: Record<MatchVerdict, string> = {
  strong_fit: "Strong fit",
  partial_fit: "Partial fit",
  weak_fit: "Weak fit",
  unknown: "Unscored",
};

function matchColor(pct: number) {
  if (pct >= 75) return "#3DD68C";
  if (pct >= 45) return "#E8B341";
  return "#F2555A";
}

function CandidateRow({
  candidate,
  rank,
  expanded,
  onToggle,
}: {
  candidate: MatchedCandidate;
  rank: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const panelId = `match-detail-${candidate.report_id}`;
  return (
    <div className={cn(candidate.is_best_fit && "bg-brand-500/[0.04]")}>
      <div className="flex items-center gap-4 px-5 py-3.5">
        <span className="w-6 shrink-0 text-sm tabular text-content-faint">{rank}</span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-content">
              {candidate.candidate_name || "Unknown candidate"}
            </span>
            {candidate.is_best_fit && (
              <Badge tone="brand" icon={<Trophy className="size-3" />}>
                Best fit
              </Badge>
            )}
          </div>
          <div className="truncate font-mono text-xs text-content-faint">
            {candidate.file_name}
          </div>
        </div>

        <div className="hidden w-32 shrink-0 sm:block">
          <div className="flex items-baseline justify-between">
            <span className="text-2xs text-content-faint">JD match</span>
            <span
              className="text-sm font-medium tabular"
              style={{ color: matchColor(candidate.match_percent) }}
            >
              {candidate.match_percent}%
            </span>
          </div>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-canvas-inset">
            <div
              className="h-full rounded-full"
              style={{
                width: `${candidate.match_percent}%`,
                background: matchColor(candidate.match_percent),
              }}
            />
          </div>
        </div>

        <Badge tone={VERDICT_TONE[candidate.verdict] ?? "neutral"}>
          {VERDICT_LABEL[candidate.verdict] ?? "Unscored"}
        </Badge>

        <span
          className="hidden shrink-0 lg:block"
          title="Overall credibility score, independent of JD fit"
        >
          <ScorePill score={candidate.overall_score} />
        </span>

        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={panelId}
          className="shrink-0 rounded p-1 text-content-faint transition-colors hover:text-content focus-visible:outline-none focus-visible:shadow-focus"
        >
          <ChevronDown
            aria-hidden
            className={cn("size-4 transition-transform", expanded && "rotate-180")}
          />
          <span className="sr-only">
            {expanded ? "Hide" : "Show"} match detail for {candidate.candidate_name}
          </span>
        </button>
      </div>

      {expanded && (
        <div id={panelId} className="space-y-4 border-t border-line-subtle bg-canvas-inset/40 px-5 py-4">
          {candidate.rationale && (
            <p className="text-sm leading-relaxed text-content-muted">{candidate.rationale}</p>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-positive">
                <Check aria-hidden className="size-3.5" />
                Evidenced against the JD
              </h4>
              {candidate.matching_skills.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {candidate.matching_skills.map((s) => (
                    <Badge key={s} tone="positive">{s}</Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-content-faint">None identified.</p>
              )}
            </div>

            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-caution">
                <Minus aria-hidden className="size-3.5" />
                Not evidenced
              </h4>
              {candidate.missing_skills.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {candidate.missing_skills.map((s) => (
                    <Badge key={s} tone="caution">{s}</Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-content-faint">Nothing missing.</p>
              )}
            </div>
          </div>

          <Link
            href={`/report/${candidate.report_id}`}
            className="inline-block text-xs font-medium text-brand-400 underline-offset-4 hover:underline"
          >
            Open full credibility report →
          </Link>
        </div>
      )}
    </div>
  );
}

function MatchContent() {
  const { state, upload, exportCsv, exporting, reset } = useJdMatch();
  const token = useAuthStore((s) => s.token);

  const [pending, setPending] = useState<File[]>([]);
  const [rejections, setRejections] = useState<FileRejection[]>([]);
  const [jdMode, setJdMode] = useState<"paste" | "upload" | "saved">("paste");
  const [jdText, setJdText] = useState("");
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [jdError, setJdError] = useState<string | null>(null);

  // Saved job descriptions. A role's description is written once and used
  // against every shortlist for it, often over weeks — retyping it each time
  // is where the wrong version gets pasted, and a ranking is only as good as
  // the description it ranked against.
  const [savedJds, setSavedJds] = useState<SavedJd[]>([]);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [savingName, setSavingName] = useState("");
  const [savingBusy, setSavingBusy] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  const refreshSavedJds = useCallback(async () => {
    if (!token) return;
    try {
      const res = await jdsAPI.list(token);
      setSavedJds(res.job_descriptions ?? []);
    } catch {
      // A picker that cannot load is an inconvenience, not a failure — paste
      // and upload still work, so this must not take the page down.
    }
  }, [token]);

  useEffect(() => {
    void refreshSavedJds();
  }, [refreshSavedJds]);

  async function openSavedJd(id: string) {
    if (!token) return;
    setJdError(null);
    setSavedNotice(null);
    try {
      const res = await jdsAPI.get(id, token);
      setSavedId(id);
      // Shown in the box as well as sent by id, so the recruiter can see
      // exactly what this run will be ranked against before starting it.
      setJdText(res.job_description.jd_text);
      setSavingName(res.job_description.name);
    } catch (e) {
      setJdError(
        e instanceof APIError ? e.message : "Could not open that saved job description.",
      );
    }
  }

  async function saveCurrentJd() {
    if (!token || savingBusy) return;
    const name = savingName.trim();
    const text = jdText.trim();
    if (!name || text.length < JD_MIN_CHARS) return;
    setSavingBusy(true);
    setJdError(null);
    setSavedNotice(null);
    try {
      const res = await jdsAPI.save(name, text, token);
      setSavedId(res.job_description.id);
      setSavedNotice(`Saved as "${res.job_description.name}".`);
      await refreshSavedJds();
    } catch (e) {
      setJdError(e instanceof APIError ? e.message : "Could not save that job description.");
    } finally {
      setSavingBusy(false);
    }
  }

  async function deleteSavedJd(id: string) {
    if (!token) return;
    try {
      await jdsAPI.remove(id, token);
      if (savedId === id) setSavedId(null);
      await refreshSavedJds();
    } catch (e) {
      setJdError(e instanceof APIError ? e.message : "Could not delete that job description.");
    }
  }
  const [expanded, setExpanded] = useState<string | null>(null);

  const addFiles = useCallback((accepted: File[], rejected: FileRejection[]) => {
    setRejections(rejected);
    setPending((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...accepted.filter((f) => !seen.has(`${f.name}:${f.size}`))].slice(
        0,
        MAX_FILES,
      );
    });
  }, []);

  function pickJd(file: File | undefined) {
    setJdError(null);
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["pdf", "docx", "txt"].includes(ext)) {
      setJdError("Use a PDF, DOCX or TXT file for the job description.");
      return;
    }
    if (file.size > JD_MAX_MB * 1024 * 1024) {
      setJdError(`Job description must be under ${JD_MAX_MB}MB.`);
      return;
    }
    setJdFile(file);
  }

  const jdReady =
    jdMode === "upload"
      ? Boolean(jdFile)
      : jdMode === "saved"
        ? Boolean(savedId)
        : jdText.trim().length >= JD_MIN_CHARS;
  const canRun = jdReady && pending.length > 0;

  function run() {
    if (!canRun) return;
    upload(
      pending,
      jdMode === "upload"
        ? { file: jdFile! }
        : jdMode === "saved"
          ? { savedId: savedId! }
          : { text: jdText.trim() },
    );
  }

  function startOver() {
    reset();
    setPending([]);
    setRejections([]);
    setJdText("");
    setJdFile(null);
    setSavedId(null);
    setSavedNotice(null);
    setExpanded(null);
  }

  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;
  const pct = batch && batch.total ? Math.round((batch.complete / batch.total) * 100) : 0;

  return (
    <AppShell>
      <PageHeader
        title="Match against a job description"
        description="Paste or upload a JD, add candidate resumes, and see how each one's evidenced experience lines up against the actual requirements."
        actions={
          batch && state.phase === "done" ? (
            <div className="flex gap-2">
              <Button
                icon={<Download className="size-4" />}
                loading={exporting}
                onClick={() => exportCsv(batch.batch_id)}
              >
                Export CSV
              </Button>
              <Button icon={<RotateCcw className="size-4" />} onClick={startOver}>
                New match
              </Button>
            </div>
          ) : null
        }
      />

      {state.phase === "error" && (
        <Alert tone="error" title="Match failed" className="mb-5">
          <p>{state.message}</p>
          <Button size="sm" className="mt-3" onClick={startOver}>
            Start over
          </Button>
        </Alert>
      )}

      {rejections.length > 0 && (
        <Alert tone="warning" className="mb-5" onDismiss={() => setRejections([])}>
          <ul className="space-y-0.5">
            {rejections.slice(0, 5).map((r, i) => (
              <li key={i}>
                <span className="font-mono text-xs">{r.file.name}</span> — {r.reason}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {state.phase === "idle" && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Step 1 — JD */}
          <Card className="flex h-full flex-col">
            <CardHeader
              title="1 · Job description"
              description="The requirements each candidate is measured against."
              action={
                <div
                  role="tablist"
                  aria-label="Job description input method"
                  className="flex rounded-md border border-line-strong bg-canvas-inset p-0.5"
                >
                  {(["paste", "upload", "saved"] as const).map((m) => (
                    <button
                      key={m}
                      role="tab"
                      type="button"
                      aria-selected={jdMode === m}
                      onClick={() => setJdMode(m)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                        jdMode === m
                          ? "bg-canvas-overlay text-content"
                          : "text-content-faint hover:text-content-muted",
                      )}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              }
            />
            <CardBody className="flex-1">
              {jdMode === "saved" ? (
                <div>
                  {savedJds.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-line-strong bg-canvas-inset px-4 py-8 text-center text-sm text-content-muted">
                      Nothing saved yet. Paste a job description, give it a name, and
                      it will be here for the next shortlist.
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {savedJds.map((jd) => (
                        <li
                          key={jd.id}
                          className={cn(
                            "flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors",
                            savedId === jd.id
                              ? "border-brand-500 bg-brand-500/5"
                              : "border-line hover:border-line-strong",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => void openSavedJd(jd.id)}
                            className="min-w-0 flex-1 text-left"
                            aria-pressed={savedId === jd.id}
                          >
                            <span className="block truncate text-sm font-medium text-content">
                              {jd.name}
                            </span>
                            <span className="block text-xs text-content-faint">
                              {jd.char_count.toLocaleString()} characters
                              {jd.last_used_at ? " · used before" : ""}
                            </span>
                          </button>
                          {savedId === jd.id && (
                            <span className="shrink-0 text-xs font-medium text-brand-400">
                              Selected
                            </span>
                          )}
                          <button
                            type="button"
                            onClick={() => void deleteSavedJd(jd.id)}
                            aria-label={`Delete saved job description ${jd.name}`}
                            className="shrink-0 rounded p-1 text-content-faint transition-colors hover:text-critical"
                          >
                            <Trash2 className="size-4" aria-hidden />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {savedId && (
                    <div className="mt-4 rounded-lg border border-line bg-canvas-inset p-3">
                      <p className="mb-1.5 text-xs font-medium text-content-muted">
                        This run will be ranked against:
                      </p>
                      <p className="max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-content-faint">
                        {jdText}
                      </p>
                    </div>
                  )}
                  {jdError && <p className="mt-2 text-xs text-critical">{jdError}</p>}
                </div>
              ) : jdMode === "paste" ? (
                <>
                  <Textarea
                    rows={12}
                    value={jdText}
                    onChange={(e) => {
                      setJdText(e.target.value);
                      // Editing the text means this is no longer the saved
                      // description — running against the stored id would rank
                      // the shortlist on text the recruiter just changed.
                      setSavedId(null);
                      setSavedNotice(null);
                    }}
                    placeholder="Paste the full job description — responsibilities, must-have requirements, nice-to-haves…"
                    aria-label="Job description text"
                  />
                  <p className="mt-2 text-xs text-content-faint">
                    {jdText.trim().length < JD_MIN_CHARS
                      ? `${JD_MIN_CHARS - jdText.trim().length} more characters needed`
                      : `${jdText.trim().length} characters`}
                  </p>

                  <div className="mt-4 border-t border-line-subtle pt-4">
                    <label
                      htmlFor="jd-save-name"
                      className="text-xs font-medium text-content-muted"
                    >
                      Save this for next time
                    </label>
                    <div className="mt-1.5 flex gap-2">
                      <Input
                        id="jd-save-name"
                        value={savingName}
                        onChange={(e) => setSavingName(e.target.value)}
                        placeholder="e.g. Senior Backend Engineer"
                        maxLength={100}
                      />
                      <Button
                        type="button"
                        size="sm"
                        className="shrink-0"
                        loading={savingBusy}
                        disabled={
                          !savingName.trim() || jdText.trim().length < JD_MIN_CHARS
                        }
                        onClick={() => void saveCurrentJd()}
                      >
                        Save
                      </Button>
                    </div>
                    {savedNotice && (
                      <p className="mt-2 text-xs text-positive">{savedNotice}</p>
                    )}
                    {jdError && <p className="mt-2 text-xs text-critical">{jdError}</p>}
                  </div>
                </>
              ) : (
                <div>
                  <label className="flex cursor-pointer flex-col items-center rounded-lg border border-dashed border-line-strong bg-canvas-inset px-5 py-10 text-center transition-colors hover:border-brand-500">
                    <input
                      type="file"
                      className="sr-only"
                      accept={JD_ACCEPT.join(",")}
                      onChange={(e) => pickJd(e.target.files?.[0])}
                    />
                    <span className="text-sm font-medium text-content">
                      {jdFile ? jdFile.name : "Choose a job description file"}
                    </span>
                    <span className="mt-1 text-xs text-content-faint">
                      {jdFile
                        ? formatBytes(jdFile.size)
                        : `PDF, DOCX or TXT · under ${JD_MAX_MB}MB`}
                    </span>
                  </label>
                  {jdFile && (
                    <Button size="sm" className="mt-3" onClick={() => setJdFile(null)}>
                      Remove
                    </Button>
                  )}
                  {jdError && <p className="mt-2 text-xs text-critical">{jdError}</p>}
                </div>
              )}
            </CardBody>
          </Card>

          {/* Step 2 — resumes */}
          <Card className="flex h-full flex-col">
            <CardHeader
              title="2 · Candidate resumes"
              description={`Up to ${MAX_FILES} per run.`}
              action={
                pending.length > 0 ? (
                  <span className="text-xs text-content-faint">
                    {pluralize(pending.length, "file")}
                  </span>
                ) : null
              }
            />
            <CardBody className="flex-1 space-y-3">
              <FileDropzone
                compact
                multiple
                maxFiles={MAX_FILES}
                onFiles={addFiles}
                title="Drop resumes here"
                hint="PDF or DOCX · 10MB each"
              />

              {pending.length > 0 && (
                <ul className="max-h-48 space-y-1.5 overflow-y-auto">
                  {pending.map((f, i) => (
                    <li
                      key={`${f.name}:${i}`}
                      className="flex items-center gap-2 rounded-md border border-line-subtle bg-canvas-inset px-2.5 py-1.5"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono text-xs text-content-muted">
                        {f.name}
                      </span>
                      <button
                        type="button"
                        aria-label={`Remove ${f.name}`}
                        onClick={() => setPending((p) => p.filter((_, idx) => idx !== i))}
                        className="rounded p-0.5 text-content-faint transition-colors hover:text-critical"
                      >
                        <X className="size-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <Button
                variant="primary"
                size="lg"
                fullWidth
                disabled={!canRun}
                icon={<Play className="size-4" />}
                onClick={run}
              >
                Run match
              </Button>
              {!canRun && (
                <p className="text-center text-xs text-content-faint">
                  {!jdReady
                    ? "Add a job description to continue."
                    : "Add at least one resume to continue."}
                </p>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {(state.phase === "uploading" || batch) && (
        <div className="space-y-5">
          <Card>
            <CardBody>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-sm font-semibold text-content">
                    {state.phase === "done" ? "Match complete" : "Matching candidates"}
                  </h2>
                  <p className="mt-0.5 text-xs text-content-faint">
                    {batch
                      ? `${batch.complete} of ${batch.total} analysed${batch.failed ? ` · ${batch.failed} failed` : ""}`
                      : "Uploading…"}
                  </p>
                </div>
                <span className="text-sm tabular text-content-muted">{pct}%</span>
              </div>
              <div
                className="mt-4 h-1 overflow-hidden rounded-full bg-canvas-inset"
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Match progress"
              >
                <div
                  className="h-full rounded-full bg-brand-500 transition-[width] duration-500 ease-out"
                  style={{ width: `${Math.max(pct, 2)}%` }}
                />
              </div>
            </CardBody>
          </Card>

          {batch && (
            <Card className="overflow-hidden">
              <CardHeader
                title="Ranked by fit"
                description="Match percentage reflects evidenced experience against the JD's requirements — not keyword overlap."
              />
              {batch.ranking.length === 0 ? (
                <EmptyState
                  icon={<Crosshair className="size-5" />}
                  title="No results yet"
                  description="Candidates appear here as each resume finishes."
                />
              ) : (
                <ErrorBoundary title="The ranking" resetKeys={[batch.batch_id]}>
                <div className="divide-y divide-line-subtle">
                  {batch.ranking.map((c, i) => (
                    <CandidateRow
                      key={c.report_id || i}
                      candidate={c}
                      rank={i + 1}
                      expanded={expanded === c.report_id}
                      onToggle={() =>
                        setExpanded((prev) => (prev === c.report_id ? null : c.report_id))
                      }
                    />
                  ))}
                </div>
                </ErrorBoundary>
              )}
            </Card>
          )}
        </div>
      )}
    </AppShell>
  );
}

export default function MatchPage() {
  return (
    <RequireAuth>
      <MatchContent />
    </RequireAuth>
  );
}
