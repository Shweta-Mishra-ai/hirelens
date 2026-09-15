"use client";
import { useEffect, useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, RotateCcw, FileText } from "lucide-react";
import { useAnalysis } from "@/hooks/useAnalysis";
import { useAnalysisReadiness, readinessMessage } from "@/hooks/useAnalysisReadiness";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { FileDropzone, type FileRejection } from "@/components/FileDropzone";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Feedback";
import { cn } from "@/lib/cn";

/**
 * The pipeline stages, in the order the backend reports them. Showing the real
 * stage names lets a recruiter tell "still reading the PDF" from "the model is
 * thinking", which matters when a run takes 30 seconds.
 */
const STAGES = [
  { key: "queued", label: "Queued" },
  { key: "parsing", label: "Reading the document" },
  { key: "extracting", label: "Extracting roles, skills and dates" },
  { key: "analyzing", label: "Assessing credibility" },
  { key: "complete", label: "Building the report" },
] as const;

function StageList({ currentStage, failed }: { currentStage: string; failed?: boolean }) {
  const activeIdx = Math.max(
    0,
    STAGES.findIndex((s) => s.key === currentStage),
  );

  return (
    <ol className="space-y-3">
      {STAGES.map((stage, i) => {
        const done = i < activeIdx;
        const active = i === activeIdx && !failed;
        return (
          <li key={stage.key} className="flex items-center gap-3">
            <span
              aria-hidden
              className={cn(
                "flex size-5 shrink-0 items-center justify-center rounded-full border",
                done && "border-positive-line bg-positive-soft text-positive",
                active && "border-brand-500 bg-brand-500/10 text-brand-400",
                !done && !active && "border-line text-content-faint",
              )}
            >
              {done ? (
                <Check className="size-3" strokeWidth={3} />
              ) : active ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <span className="size-1.5 rounded-full bg-current" />
              )}
            </span>
            <span
              className={cn(
                "text-sm",
                done && "text-content-muted",
                active && "font-medium text-content",
                !done && !active && "text-content-faint",
              )}
            >
              {stage.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function AnalyzeContent() {
  const router = useRouter();
  const { state, analyze, reset } = useAnalysis();
  const readiness = useAnalysisReadiness();
  const readinessWarning = readinessMessage(readiness);
  const [rejections, setRejections] = useState<FileRejection[]>([]);

  useEffect(() => {
    if (state.phase === "complete" && state.report?.id) {
      router.push(`/report/${state.report.id}`);
    }
  }, [state, router]);

  const handleFiles = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      setRejections(rejected);
      if (accepted[0]) analyze(accepted[0]);
    },
    [analyze],
  );

  const busy = state.phase === "uploading" || state.phase === "analyzing";
  const progress =
    state.phase === "analyzing" ? state.job.progress : state.phase === "complete" ? 100 : 0;

  return (
    <AppShell width="narrow">
      <PageHeader
        title="Analyze a resume"
        description="Upload a PDF or DOCX. HireLens reads the actual document text and returns a credibility assessment in which every flag quotes the sentence that raised it."
      />

      {readinessWarning && (
        <Alert tone={readinessWarning.tone} title={readinessWarning.title} className="mb-5">
          {readinessWarning.body}
        </Alert>
      )}

      {rejections.length > 0 && (
        <Alert tone="warning" className="mb-5" onDismiss={() => setRejections([])}>
          <ul className="space-y-0.5">
            {rejections.map((r, i) => (
              <li key={i}>
                <span className="font-mono text-xs">{r.file.name}</span> — {r.reason}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {state.phase === "error" && (
        <Alert tone="error" title="Analysis failed" className="mb-5">
          <p>{state.message}</p>
          <Button
            size="sm"
            className="mt-3"
            icon={<RotateCcw className="size-3.5" />}
            onClick={() => {
              setRejections([]);
              reset();
            }}
          >
            Try another file
          </Button>
        </Alert>
      )}

      {busy ? (
        <Card>
          <CardBody>
            <div className="flex items-center gap-3">
              <FileText aria-hidden className="size-4 shrink-0 text-content-faint" />
              <span className="min-w-0 flex-1 truncate font-mono text-sm text-content-muted">
                {state.phase === "analyzing" ? state.job.file_name : "Uploading…"}
              </span>
              <span className="shrink-0 text-sm tabular text-content-muted">{progress}%</span>
            </div>

            <div
              className="mt-3 h-1 overflow-hidden rounded-full bg-canvas-inset"
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Analysis progress"
            >
              <div
                className="h-full rounded-full bg-brand-500 transition-[width] duration-500 ease-out"
                style={{ width: `${Math.max(progress, 4)}%` }}
              />
            </div>

            <div className="mt-6 border-t border-line-subtle pt-5">
              <StageList
                currentStage={state.phase === "analyzing" ? state.job.stage : "queued"}
              />
            </div>

            <p className="mt-5 text-xs text-content-faint">
              This usually takes 10–30 seconds. You can leave this page — the report
              will be waiting on your dashboard.
            </p>
          </CardBody>
        </Card>
      ) : state.phase !== "error" ? (
        <FileDropzone
          onFiles={handleFiles}
          disabled={readiness.state === "no_provider" || readiness.state === "unreachable"}
          title="Drop a resume here"
          hint="PDF or DOCX, up to 10MB. The file must have selectable text — scanned images cannot be read."
        />
      ) : null}

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {[
          {
            title: "Six scored dimensions",
            body: "Timeline, skills consistency, education, project authenticity, resume quality and content authenticity — each with the model's written reasoning.",
          },
          {
            title: "Evidence, not verdicts",
            body: "Every flag quotes the exact resume text that triggered it, so you can disagree with it.",
          },
          {
            title: "Targeted interview questions",
            body: "Questions written against this candidate's specific flags, not a generic bank.",
          },
          {
            title: "Public-record checks",
            body: "Run live GitHub, institution and certificate verification from the report once it's built.",
          },
        ].map((f) => (
          <Card key={f.title} className="p-4">
            <h3 className="text-sm font-medium text-content">{f.title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-content-faint">{f.body}</p>
          </Card>
        ))}
      </div>

      <p className="mt-6 text-xs leading-relaxed text-content-faint">
        Resumes are sent to the configured AI provider for analysis and stored against
        your account. Only upload candidate documents you are permitted to process, and
        treat every result as a prompt to investigate rather than a decision.
      </p>
    </AppShell>
  );
}

export default function AnalyzePage() {
  return (
    <RequireAuth>
      <AnalyzeContent />
    </RequireAuth>
  );
}
