"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useBulkAnalysis } from "@/hooks/useBulkAnalysis";
import { bulkAPI, APIError } from "@/lib/api";
import type { RankedCandidate, DuplicateCheckResult } from "@/types";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";

const MAX_FILES = 50;
const MAX_MB = 10;

function scoreColor(n: number) {
  if (n >= 75) return "#6E9974";
  if (n >= 55) return "#D4AC5C";
  return "#D46A4C";
}

function statusBadge(status: string) {
  const m: Record<string, { label: string; color: string }> = {
    queued:   { label: "Queued",     color: "#9C9483" },
    running:  { label: "Analyzing…", color: "#6E90AC" },
    complete: { label: "Done",       color: "#6E9974" },
    failed:   { label: "Failed",     color: "#D46A4C" },
  };
  return m[status] || { label: status, color: "#9C9483" };
}

export default function BulkUploadPage() {
  const router = useRouter();
  const { token, hasHydrated } = useAuthStore();
  const { state, upload, uploadFromAts, exportCsv, exporting, reset } = useBulkAnalysis();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);
  const [dupResult, setDupResult] = useState<DuplicateCheckResult | null>(null);
  const [dupLoading, setDupLoading] = useState(false);
  const [dupError, setDupError] = useState<string | null>(null);

  useEffect(() => {
    if (hasHydrated && !token) router.replace("/login");
  }, [hasHydrated, token, router]);

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
        setPickError(`Max ${MAX_FILES} files per batch — extra files were dropped.`);
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

  const isBusy = state.phase === "uploading" || state.phase === "processing";
  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;

  return (
    <div style={{ minHeight: "100vh", background: "#0D0C0A" }}>
      {/* Navbar */}
      <nav style={{ height: 54, borderBottom: "1px solid #2A251C", display: "flex", alignItems: "center", paddingInline: 24, gap: 16, position: "sticky", top: 0, background: "rgba(13,12,10,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#3E5C76,#3E5C76)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EDE6D6", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <span style={{ color: "#2A251C" }}>|</span>
        <span style={{ fontSize: 13, color: "#9C9483" }}>Bulk Upload</span>
        <div style={{ flex: 1 }} />
        <Link href="/analyze" style={{ fontSize: 12, color: "#9C9483", textDecoration: "none" }}>Single upload →</Link>
      </nav>

      <div style={{ maxWidth: 860, margin: "0 auto", padding: "40px 24px" }}>

        {/* ── IDLE: multi-file picker ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <h1 style={{ fontSize: 26, fontWeight: 900, color: "#EDE6D6", margin: "0 0 8px", letterSpacing: -1 }}>
                Bulk CV Upload &amp; Ranking
              </h1>
              <p style={{ fontSize: 14, color: "#A79E8C", margin: 0, lineHeight: 1.6 }}>
                Upload up to {MAX_FILES} resumes at once. HireLens analyzes them in parallel<br />
                and auto-ranks candidates by credibility score.
              </p>
            </div>

            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: "2px dashed #1E3450", borderRadius: 20, padding: "44px 32px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 14,
                cursor: "pointer", background: "#131110", transition: "all .2s", textAlign: "center",
              }}
              onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#3E5C76"; (e.currentTarget as HTMLElement).style.background = "rgba(62,92,118,0.06)"; }}
              onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#1E3450"; (e.currentTarget as HTMLElement).style.background = "#131110"; }}
            >
              <input
                ref={inputRef} type="file" accept=".pdf,.docx" multiple style={{ display: "none" }}
                onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ""; }}
              />
              <div style={{ width: 64, height: 64, borderRadius: 20, background: "rgba(62,92,118,0.12)", border: "1.5px solid rgba(62,92,118,0.35)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26 }}>🗂️</div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#EDE6D6", marginBottom: 4 }}>Drop resumes here, or click to browse</div>
                <div style={{ fontSize: 12, color: "#9C9483" }}>PDF or DOCX · Max {MAX_MB}MB each · Up to {MAX_FILES} files</div>
              </div>
            </div>

            {/* ATS CSV import — alternate source, same downstream pipeline */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "14px 0" }}>
              <div style={{ flex: 1, height: 1, background: "#2A251C" }} />
              <span style={{ fontSize: 11, color: "#6B6355", textTransform: "uppercase", letterSpacing: 1 }}>or</span>
              <div style={{ flex: 1, height: 1, background: "#2A251C" }} />
            </div>
            <label
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                padding: "12px 20px", borderRadius: 10, border: "1px dashed #2A251C",
                background: "#131110", cursor: "pointer", fontSize: 13, color: "#9C9483",
              }}
            >
              <input
                type="file" accept=".csv" style={{ display: "none" }}
                onChange={(e) => { if (e.target.files?.[0]) uploadFromAts(e.target.files[0]); e.target.value = ""; }}
              />
              📋 Import candidates from a Greenhouse / Lever / Workday CSV export
            </label>

            {pickError && (
              <div style={{ marginTop: 12, padding: "10px 14px", background: "rgba(177,66,38,0.08)", border: "1px solid rgba(177,66,38,.3)", borderRadius: 10, fontSize: 12, color: "#D46A4C" }}>
                {pickError}
              </div>
            )}

            {pending.length > 0 && (
              <div style={{ marginTop: 20 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: "#EDE6D6" }}>{pending.length} file{pending.length > 1 ? "s" : ""} selected</span>
                  <button onClick={() => setPending([])} style={{ background: "none", border: "none", color: "#9C9483", fontSize: 12, cursor: "pointer" }}>Clear all</button>
                </div>
                <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, background: "#17140F", border: "1px solid #2A251C", borderRadius: 12, padding: 8 }}>
                  {pending.map((f, i) => (
                    <div key={`${f.name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8, background: "#131110" }}>
                      <span style={{ fontSize: 14 }}>📄</span>
                      <span style={{ fontSize: 12, color: "#D9D2C0", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                      <span style={{ fontSize: 11, color: "#9C9483", fontFamily: "monospace" }}>{(f.size / 1024 / 1024).toFixed(1)}MB</span>
                      <button onClick={() => removeFile(i)} style={{ background: "none", border: "none", color: "#9C9483", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>✕</button>
                    </div>
                  ))}
                </div>

                <button
                  onClick={startUpload}
                  style={{ marginTop: 16, width: "100%", padding: "13px 0", borderRadius: 12, border: "none", cursor: "pointer", background: "linear-gradient(135deg,#3E5C76,#2C4258)", color: "#EDE6D6", fontWeight: 700, fontSize: 14, fontFamily: "inherit" }}
                >
                  Analyze {pending.length} Resume{pending.length > 1 ? "s" : ""}
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── UPLOADING ── */}
        {state.phase === "uploading" && (
          <div className="animate-fade-up" style={{ textAlign: "center", padding: "40px 0" }}>
            <div style={{ width: 56, height: 56, border: "3px solid #2A251C", borderTopColor: "#3E5C76", borderRadius: "50%", margin: "0 auto 20px", animation: "spin 1s linear infinite" }} />
            <div style={{ fontSize: 16, fontWeight: 700, color: "#EDE6D6", marginBottom: 6 }}>Uploading {pending.length} resumes…</div>
            <div style={{ fontSize: 13, color: "#9C9483" }}>Sending to HireLens API</div>
          </div>
        )}

        {/* ── PROCESSING / DONE ── */}
        {batch && (
          <div className="animate-fade-up">
            {/* Overall progress */}
            <div style={{ background: "#17140F", border: "1px solid #2A251C", borderRadius: 16, padding: "20px 24px", marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: "#EDE6D6" }}>
                  {batch.is_done ? "Batch complete" : "Analyzing batch…"}
                </span>
                <span style={{ fontSize: 12, color: "#A79E8C", fontFamily: "monospace" }}>
                  {batch.complete + batch.failed}/{batch.total} done
                </span>
              </div>
              <div style={{ height: 6, background: "#2A251C", borderRadius: 99, overflow: "hidden" }}>
                <div style={{
                  height: "100%", borderRadius: 99, transition: "width .5s ease",
                  width: `${Math.max(4, Math.round(((batch.complete + batch.failed) / Math.max(1, batch.total)) * 100))}%`,
                  background: "linear-gradient(90deg,#3E5C76,#6E90AC)",
                }} />
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 12, fontSize: 12, color: "#9C9483" }}>
                <span>🕓 Queued: <strong style={{ color: "#A79E8C" }}>{batch.queued}</strong></span>
                <span>⚙️ Running: <strong style={{ color: "#6E90AC" }}>{batch.running}</strong></span>
                <span>✓ Complete: <strong style={{ color: "#6E9974" }}>{batch.complete}</strong></span>
                {batch.failed > 0 && <span>✕ Failed: <strong style={{ color: "#D46A4C" }}>{batch.failed}</strong></span>}
              </div>
            </div>

            {/* Per-file rows while still processing */}
            {!batch.is_done && (
              <div style={{ background: "#17140F", border: "1px solid #2A251C", borderRadius: 16, padding: 12, marginBottom: 20, maxHeight: 280, overflowY: "auto" }}>
                {batch.jobs.map((j) => {
                  const b = statusBadge(j.status);
                  return (
                    <div key={j.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 10px", borderRadius: 8 }}>
                      <span style={{ fontSize: 13 }}>📄</span>
                      <span style={{ fontSize: 12, color: "#D9D2C0", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.file_name}</span>
                      {j.status === "running" && <span style={{ fontSize: 11, color: "#9C9483", fontFamily: "monospace" }}>{j.progress}%</span>}
                      <span style={{ fontSize: 11, fontWeight: 700, color: b.color }}>{b.label}</span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Ranking table — updates live as candidates finish */}
            {batch.ranking.length > 0 && (
              <div style={{ background: "#17140F", border: "1px solid #2A251C", borderRadius: 16, overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px", borderBottom: "1px solid #2A251C" }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "#EDE6D6" }}>Ranked Candidates</span>
                  <button
                    onClick={() => exportCsv(batch.batch_id)}
                    disabled={exporting}
                    style={{ padding: "8px 16px", borderRadius: 10, border: "1px solid #2A251C", background: "#131110", color: "#D9D2C0", fontSize: 12, fontWeight: 700, cursor: exporting ? "default" : "pointer", opacity: exporting ? 0.6 : 1 }}
                  >
                    {exporting ? "Exporting…" : "⬇ Export CSV"}
                  </button>
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ textAlign: "left", fontSize: 11, color: "#9C9483", textTransform: "uppercase", letterSpacing: .5 }}>
                        <th style={{ padding: "10px 20px" }}>Rank</th>
                        <th style={{ padding: "10px 12px" }}>Candidate</th>
                        <th style={{ padding: "10px 12px" }}>File</th>
                        <th style={{ padding: "10px 12px" }}>Score</th>
                        <th style={{ padding: "10px 12px" }}>Recommendation</th>
                        <th style={{ padding: "10px 20px" }} />
                      </tr>
                    </thead>
                    <tbody>
                      {batch.ranking.map((c: RankedCandidate) => {
                        return (
                          <tr key={c.report_id} style={{ borderTop: "1px solid #2A251C" }}>
                            <td style={{ padding: "12px 20px", fontSize: 13, fontWeight: 800, color: c.rank <= 3 ? "#D4AC5C" : "#9C9483" }}>#{c.rank}</td>
                            <td style={{ padding: "12px 12px", fontSize: 13, color: "#EDE6D6", fontWeight: 600 }}>{c.candidate_name}</td>
                            <td style={{ padding: "12px 12px", fontSize: 11, color: "#9C9483", fontFamily: "monospace" }}>{c.file_name}</td>
                            <td style={{ padding: "12px 12px" }}>
                              <span className="font-display" style={{ fontSize: 15, fontWeight: 700, color: scoreColor(c.overall_score) }}>{c.overall_score}</span>
                            </td>
                            <td style={{ padding: "12px 12px" }}>
                              <VerdictChip verdict={verdictFromRecommendation(c.recommendation)} />
                            </td>
                            <td style={{ padding: "12px 20px" }}>
                              <Link href={`/report/${c.report_id}`} style={{ fontSize: 12, color: "#6E90AC", textDecoration: "none", fontWeight: 700 }}>View →</Link>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Cross-candidate duplicate/template detection */}
            {batch.is_done && batch.ranking.length >= 2 && (
              <div style={{ marginTop: 16, background: "#17140F", border: "1px solid #2A251C", borderRadius: 6, padding: "16px 20px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: dupResult || dupError ? 12 : 0 }}>
                  <div>
                    <div className="font-display" style={{ fontSize: 14, fontWeight: 600, color: "#EDE6D6" }}>Cross-Candidate Duplicate Check</div>
                    <div style={{ fontSize: 11, color: "#6B6355", marginTop: 2 }}>Flags candidates whose resume content is suspiciously similar to each other</div>
                  </div>
                  <button
                    onClick={() => checkDuplicates(batch.batch_id)}
                    disabled={dupLoading}
                    style={{ padding: "8px 16px", borderRadius: 4, border: "1px solid #2A251C", background: "#131110", color: "#D9D2C0", fontSize: 12, fontWeight: 700, cursor: dupLoading ? "default" : "pointer", opacity: dupLoading ? 0.6 : 1, whiteSpace: "nowrap" }}
                  >
                    {dupLoading ? "Checking…" : "Run Check"}
                  </button>
                </div>

                {dupError && <div style={{ fontSize: 12, color: "#D46A4C" }}>{dupError}</div>}

                {dupResult && (
                  <div>
                    {dupResult.clusters.length === 0 ? (
                      <div style={{ fontSize: 12, color: "#6E9974" }}>
                        ✓ No suspiciously-similar candidates found among {dupResult.candidates_compared} compared.
                      </div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {dupResult.clusters.map((cluster, i) => (
                          <div key={i} style={{ background: "rgba(177,66,38,.06)", border: "1px solid rgba(177,66,38,.25)", borderRadius: 4, padding: "10px 14px" }}>
                            <div style={{ fontSize: 12, fontWeight: 700, color: "#D46A4C", marginBottom: 6 }}>
                              {Math.round(cluster.similarity * 100)}% similar content
                            </div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                              {cluster.members.map((m) => (
                                <span key={m.id} style={{ fontSize: 11, color: "#D9D2C0", background: "#131110", padding: "3px 10px", borderRadius: 999 }}>{m.name}</span>
                              ))}
                            </div>
                          </div>
                        ))}
                        <div style={{ fontSize: 11, color: "#6B6355", lineHeight: 1.6 }}>{dupResult.note}</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {batch.is_done && (
              <div style={{ marginTop: 20, textAlign: "center" }}>
                <button onClick={reset} style={{ padding: "11px 28px", borderRadius: 12, border: "1px solid #2A251C", cursor: "pointer", background: "#17140F", color: "#D9D2C0", fontWeight: 700, fontSize: 13, fontFamily: "inherit" }}>
                  Upload Another Batch
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── ERROR ── */}
        {state.phase === "error" && (
          <div className="animate-fade-up" style={{ textAlign: "center" }}>
            <div style={{ background: "#17140F", border: "1px solid rgba(177,66,38,.3)", borderRadius: 20, padding: "44px 32px" }}>
              <div style={{ fontSize: 40, marginBottom: 16 }}>⚠</div>
              <div style={{ fontSize: 17, fontWeight: 700, color: "#EDE6D6", marginBottom: 10 }}>Bulk Upload Failed</div>
              <div style={{ fontSize: 13, color: "#A79E8C", lineHeight: 1.65, marginBottom: 28 }}>{state.message}</div>
              <button onClick={reset} style={{ padding: "11px 28px", borderRadius: 12, border: "none", cursor: "pointer", background: "linear-gradient(135deg,#3E5C76,#2C4258)", color: "#EDE6D6", fontWeight: 700, fontSize: 14, fontFamily: "inherit" }}>
                Try Again
              </button>
            </div>
          </div>
        )}

      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .animate-fade-up { animation: fadeUp .3s ease forwards; }
        @keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }
      `}</style>
    </div>
  );
}
