"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useBulkAnalysis } from "@/hooks/useBulkAnalysis";
import { bulkAPI, APIError } from "@/lib/api";
import {
  Search,
  Files,
  AlertCircle,
  X,
  Download,
  CheckCircle2,
} from "lucide-react";
import type { DuplicateCheckResult, RankedCandidate } from "@/types";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";
import { color, gradient, radius } from "@/lib/design-tokens";
import { Card, Button, PageShell } from "@/components/ui/primitives";
import { AppNavbar } from "@/components/ui/AppNavbar";

const MAX_FILES = 50;
const MAX_MB = 10;

function scoreColor(n: number) {
  if (n >= 75) return color.success;
  if (n >= 55) return color.warning;
  return color.danger;
}

export default function BulkUploadPage() {
  const router = useRouter();
  const { token, sessionChecked } = useAuthStore();
  const { state, upload, exportCsv, exporting, exportError, reset } = useBulkAnalysis();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);
  const [dupResult, setDupResult] = useState<DuplicateCheckResult | null>(null);
  const [dupLoading, setDupLoading] = useState(false);
  const [dupError, setDupError] = useState<string | null>(null);

  useEffect(() => {
    if (sessionChecked && !token) router.replace("/login");
  }, [sessionChecked, token, router]);

  const addFiles = useCallback((incoming: FileList | File[]) => {
    setPickError(null);
    const arr = Array.from(incoming);
    const valid: File[] = [];
    const rejected: string[] = [];

    for (const f of arr) {
      const ext = f.name.split(".").pop()?.toLowerCase();
      if (!["pdf", "docx"].includes(ext || "")) { rejected.push(`${f.name} (unsupported type)`); continue; }
      if (f.size > MAX_MB * 1024 * 1024) { rejected.push(`${f.name} (over ${MAX_MB}MB)`); continue; }
      valid.push(f);
    }

    setPending((prev) => {
      const combined = [...prev, ...valid];
      if (combined.length > MAX_FILES) {
        setPickError(`Max ${MAX_FILES} files per batch — extra files dropped.`);
        return combined.slice(0, MAX_FILES);
      }
      return combined;
    });

    if (rejected.length) {
      setPickError((prev) => (prev ? prev + " " : "") + `Skipped: ${rejected.slice(0, 3).join(", ")}${rejected.length > 3 ? ` +${rejected.length - 3} more` : ""}`);
    }
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  }, [addFiles]);

  const removeFile = (idx: number) => setPending((prev) => prev.filter((_, i) => i !== idx));

  const startUpload = () => {
    if (pending.length === 0) return;
    upload(pending);
  };

  const checkDuplicates = async (batchId: string) => {
    if (!token) return;
    setDupLoading(true);
    setDupError(null);
    try {
      const result = await bulkAPI.checkDuplicates(batchId, token);
      setDupResult(result);
    } catch (e) {
      setDupError(e instanceof APIError ? e.message : "Could not run duplicate check.");
    } finally {
      setDupLoading(false);
    }
  };

  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;

  return (
    <PageShell>
      <AppNavbar />

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
        {/* ── IDLE: Upload form ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <h1 className="font-display" style={{ fontSize: 28, fontWeight: 600, color: color.textPrimary, margin: "0 0 10px" }}>Bulk resume analysis</h1>
              <p style={{ fontSize: 15, color: color.textMuted, margin: 0 }}>Upload up to {MAX_FILES} resumes at once — ranked, scored, and cross-checked for duplicates.</p>
            </div>

            <div
              onDragOver={e => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: `1.5px dashed ${color.border}`,
                borderRadius: radius.lg, padding: "44px 32px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 16,
                cursor: "pointer", background: color.surface,
                textAlign: "center",
                transition: "border-color 0.15s ease",
              }}
            >
              <input
                ref={inputRef}
                type="file"
                multiple
                accept=".pdf,.docx"
                style={{ display: "none" }}
                onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); }}
              />
              <div style={{ width: 60, height: 60, borderRadius: radius.lg, background: color.surfaceRaised, border: `1px solid ${color.border}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Files size={28} color={color.brandLight} />
              </div>
              <div>
                <div className="font-display" style={{ fontSize: 17, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>Drop candidate resumes here</div>
                <div style={{ fontSize: 13, color: color.textMuted }}>PDF or DOCX · Max {MAX_FILES} files per batch · Under {MAX_MB}MB each</div>
              </div>
            </div>

            {pickError && (
              <div style={{ marginTop: 16, padding: "12px 16px", borderRadius: radius.md, background: color.dangerBg, border: `1px solid ${color.dangerBorder}`, color: color.danger, fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{pickError}</span>
              </div>
            )}

            {/* Pending files list */}
            {pending.length > 0 && (
              <Card style={{ marginTop: 24, padding: 24 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>Selected Files ({pending.length}/{MAX_FILES})</span>
                  <Button onClick={startUpload}>Start Batch Analysis</Button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
                  {pending.map((f, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", background: "rgba(15, 23, 42, 0.6)", border: `1px solid ${color.borderSubtle}`, borderRadius: radius.sm, fontSize: 12 }}>
                      <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 160, color: color.textSecondary }}>{f.name}</span>
                      <button onClick={(e) => { e.stopPropagation(); removeFile(i); }} style={{ background: "none", border: "none", color: color.danger, cursor: "pointer", display: "flex", alignItems: "center" }}>
                        <X size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        )}

        {/* ── Processing / Results ── */}
        {(state.phase === "uploading" || state.phase === "processing" || state.phase === "done") && batch && (
          <div className="animate-fade-up">
            <Card style={{ padding: 28, marginBottom: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>Batch Progress</div>
                  <div style={{ fontSize: 13, color: color.textMuted }}>{batch.complete} of {batch.total} resumes analyzed</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    {state.phase === "done" && (
                      <>
                        <Button variant="secondary" onClick={() => checkDuplicates(batch.batch_id)} disabled={dupLoading}>
                          <Search size={13} />
                          <span>{dupLoading ? "Checking…" : "Check Duplicates"}</span>
                        </Button>
                        <Button onClick={() => exportCsv(batch.batch_id)} disabled={exporting}>
                          <Download size={13} />
                          <span>{exporting ? "Exporting…" : "Export CSV"}</span>
                        </Button>
                        <Button variant="ghost" onClick={() => { reset(); setPending([]); }}>New Batch</Button>
                      </>
                    )}
                  </div>
                  {(exportError || dupError) && (
                    <div style={{ fontSize: 11, color: color.danger }}>{exportError || dupError}</div>
                  )}
                </div>
              </div>

              {/* Progress bar */}
              <div style={{ height: 6, background: "rgba(237, 237, 234, 0.08)", borderRadius: radius.pill, overflow: "hidden" }}>
                <div style={{ height: "100%", background: `linear-gradient(90deg, ${color.brand}, ${color.success})`, width: `${batch.total ? Math.round((batch.complete / batch.total) * 100) : 0}%`, transition: "width 0.4s ease" }} />
              </div>
            </Card>

            {/* Duplicate check results card */}
            {dupResult && (
              <Card style={{ border: `1px solid ${color.warningBorder}`, padding: 24, marginBottom: 24 }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: color.warning, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
                  <Search size={15} color={color.warning} />
                  <span>Duplicate Candidate Scan</span>
                </div>
                {dupResult.clusters.length === 0 ? (
                  <div style={{ fontSize: 13, color: color.success, display: "flex", alignItems: "center", gap: 6 }}>
                    <CheckCircle2 size={15} color={color.success} />
                    <span>No duplicate candidates detected in this batch ({dupResult.candidates_compared} compared).</span>
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {dupResult.clusters.map((c, i) => (
                      <div key={i} style={{ fontSize: 13, color: color.textSecondary, background: "rgba(15,23,42,0.6)", padding: "10px 14px", borderRadius: radius.sm }}>
                        <span style={{ color: color.danger, fontWeight: 600 }}>
                          Duplicate Group ({c.members.length}, {Math.round(c.similarity * 100)}% similar):
                        </span>{" "}
                        {c.members.map((m) => m.name).join(" & ")}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            )}

            {/* Candidate Rankings Table */}
            <Card style={{ overflow: "hidden" }}>
              <div style={{ padding: "16px 24px", borderBottom: `1px solid ${color.border}`, fontSize: 13, fontWeight: 600, color: color.textSecondary }}>
                Candidate Credibility Rankings ({batch.ranking.length})
              </div>
              {batch.ranking.map((c: RankedCandidate, i: number) => (
                <div key={c.report_id || i} style={{ display: "flex", alignItems: "center", padding: "14px 24px", gap: 16, borderBottom: i < batch.ranking.length - 1 ? `1px solid ${color.borderSubtle}` : "none", flexWrap: "wrap" }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: color.textFaint, width: 24 }}>#{i + 1}</div>
                  <div style={{ flex: 1, minWidth: 120 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>{c.candidate_name || "Unknown"}</div>
                    <div style={{ fontSize: 12, color: color.textMuted, fontFamily: "var(--font-mono), monospace" }}>{c.file_name}</div>
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 600, color: scoreColor(c.overall_score), fontFamily: "var(--font-mono), monospace" }}>{c.overall_score}</div>
                  <VerdictChip verdict={verdictFromRecommendation(c.recommendation)} />
                  <Link href={`/report/${c.report_id}`} style={{ padding: "6px 14px", borderRadius: radius.sm, background: color.surfaceRaised, border: `1px solid ${color.border}`, color: color.brandLight, fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
                    View report
                  </Link>
                </div>
              ))}
            </Card>
          </div>
        )}
      </div>
    </PageShell>
  );
}
