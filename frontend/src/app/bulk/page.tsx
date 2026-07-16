"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useBulkAnalysis } from "@/hooks/useBulkAnalysis";
import type { RankedCandidate } from "@/types";

const MAX_FILES = 50;
const MAX_MB = 10;

function scoreColor(n: number) {
  if (n >= 75) return "#10B981";
  if (n >= 55) return "#FBBF24";
  return "#F87171";
}

function recBadge(r: string) {
  const m: Record<string, { label: string; color: string; bg: string }> = {
    recommended:   { label: "Recommended",   color: "#10B981", bg: "rgba(5,150,105,0.12)" },
    manual_review: { label: "Manual Review", color: "#FBBF24", bg: "rgba(217,119,6,0.12)" },
    high_risk:     { label: "High Risk",     color: "#F87171", bg: "rgba(220,38,38,0.12)" },
  };
  return m[r] || m.manual_review;
}

function statusBadge(status: string) {
  const m: Record<string, { label: string; color: string }> = {
    queued:   { label: "Queued",     color: "#64748B" },
    running:  { label: "Analyzing…", color: "#4B8DFF" },
    complete: { label: "Done",       color: "#10B981" },
    failed:   { label: "Failed",     color: "#F87171" },
  };
  return m[status] || { label: status, color: "#64748B" };
}

export default function BulkUploadPage() {
  const router = useRouter();
  const { token, hasHydrated } = useAuthStore();
  const { state, upload, exportCsv, exporting, reset } = useBulkAnalysis();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);

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

  const isBusy = state.phase === "uploading" || state.phase === "processing";
  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;

  return (
    <div style={{ minHeight: "100vh", background: "#060F1A" }}>
      {/* Navbar */}
      <nav style={{ height: 54, borderBottom: "1px solid #172840", display: "flex", alignItems: "center", paddingInline: 24, gap: 16, position: "sticky", top: 0, background: "rgba(6,15,26,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EFF6FF", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <span style={{ color: "#172840" }}>|</span>
        <span style={{ fontSize: 13, color: "#64748B" }}>Bulk Upload</span>
        <div style={{ flex: 1 }} />
        <Link href="/analyze" style={{ fontSize: 12, color: "#64748B", textDecoration: "none" }}>Single upload →</Link>
      </nav>

      <div style={{ maxWidth: 860, margin: "0 auto", padding: "40px 24px" }}>

        {/* ── IDLE: multi-file picker ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <h1 style={{ fontSize: 26, fontWeight: 900, color: "#EFF6FF", margin: "0 0 8px", letterSpacing: -1 }}>
                Bulk CV Upload &amp; Ranking
              </h1>
              <p style={{ fontSize: 14, color: "#94A3B8", margin: 0, lineHeight: 1.6 }}>
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
                cursor: "pointer", background: "#0A1525", transition: "all .2s", textAlign: "center",
              }}
              onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#1D6AFF"; (e.currentTarget as HTMLElement).style.background = "rgba(29,106,255,0.06)"; }}
              onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#1E3450"; (e.currentTarget as HTMLElement).style.background = "#0A1525"; }}
            >
              <input
                ref={inputRef} type="file" accept=".pdf,.docx" multiple style={{ display: "none" }}
                onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ""; }}
              />
              <div style={{ width: 64, height: 64, borderRadius: 20, background: "rgba(29,106,255,0.12)", border: "1.5px solid rgba(29,106,255,0.35)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26 }}>🗂️</div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#EFF6FF", marginBottom: 4 }}>Drop resumes here, or click to browse</div>
                <div style={{ fontSize: 12, color: "#64748B" }}>PDF or DOCX · Max {MAX_MB}MB each · Up to {MAX_FILES} files</div>
              </div>
            </div>

            {pickError && (
              <div style={{ marginTop: 12, padding: "10px 14px", background: "rgba(220,38,38,0.08)", border: "1px solid rgba(220,38,38,.3)", borderRadius: 10, fontSize: 12, color: "#F87171" }}>
                {pickError}
              </div>
            )}

            {pending.length > 0 && (
              <div style={{ marginTop: 20 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: "#EFF6FF" }}>{pending.length} file{pending.length > 1 ? "s" : ""} selected</span>
                  <button onClick={() => setPending([])} style={{ background: "none", border: "none", color: "#64748B", fontSize: 12, cursor: "pointer" }}>Clear all</button>
                </div>
                <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, background: "#0E1C2E", border: "1px solid #172840", borderRadius: 12, padding: 8 }}>
                  {pending.map((f, i) => (
                    <div key={`${f.name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8, background: "#0A1525" }}>
                      <span style={{ fontSize: 14 }}>📄</span>
                      <span style={{ fontSize: 12, color: "#CBD5E1", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                      <span style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace" }}>{(f.size / 1024 / 1024).toFixed(1)}MB</span>
                      <button onClick={() => removeFile(i)} style={{ background: "none", border: "none", color: "#64748B", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>✕</button>
                    </div>
                  ))}
                </div>

                <button
                  onClick={startUpload}
                  style={{ marginTop: 16, width: "100%", padding: "13px 0", borderRadius: 12, border: "none", cursor: "pointer", background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 14, fontFamily: "inherit" }}
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
            <div style={{ width: 56, height: 56, border: "3px solid #172840", borderTopColor: "#1D6AFF", borderRadius: "50%", margin: "0 auto 20px", animation: "spin 1s linear infinite" }} />
            <div style={{ fontSize: 16, fontWeight: 700, color: "#EFF6FF", marginBottom: 6 }}>Uploading {pending.length} resumes…</div>
            <div style={{ fontSize: 13, color: "#64748B" }}>Sending to HireLens API</div>
          </div>
        )}

        {/* ── PROCESSING / DONE ── */}
        {batch && (
          <div className="animate-fade-up">
            {/* Overall progress */}
            <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, padding: "20px 24px", marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: "#EFF6FF" }}>
                  {batch.is_done ? "Batch complete" : "Analyzing batch…"}
                </span>
                <span style={{ fontSize: 12, color: "#94A3B8", fontFamily: "monospace" }}>
                  {batch.complete + batch.failed}/{batch.total} done
                </span>
              </div>
              <div style={{ height: 6, background: "#172840", borderRadius: 99, overflow: "hidden" }}>
                <div style={{
                  height: "100%", borderRadius: 99, transition: "width .5s ease",
                  width: `${Math.max(4, Math.round(((batch.complete + batch.failed) / Math.max(1, batch.total)) * 100))}%`,
                  background: "linear-gradient(90deg,#1D6AFF,#22D3EE)",
                }} />
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 12, fontSize: 12, color: "#64748B" }}>
                <span>🕓 Queued: <strong style={{ color: "#94A3B8" }}>{batch.queued}</strong></span>
                <span>⚙️ Running: <strong style={{ color: "#4B8DFF" }}>{batch.running}</strong></span>
                <span>✓ Complete: <strong style={{ color: "#10B981" }}>{batch.complete}</strong></span>
                {batch.failed > 0 && <span>✕ Failed: <strong style={{ color: "#F87171" }}>{batch.failed}</strong></span>}
              </div>
            </div>

            {/* Per-file rows while still processing */}
            {!batch.is_done && (
              <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, padding: 12, marginBottom: 20, maxHeight: 280, overflowY: "auto" }}>
                {batch.jobs.map((j) => {
                  const b = statusBadge(j.status);
                  return (
                    <div key={j.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 10px", borderRadius: 8 }}>
                      <span style={{ fontSize: 13 }}>📄</span>
                      <span style={{ fontSize: 12, color: "#CBD5E1", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.file_name}</span>
                      {j.status === "running" && <span style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace" }}>{j.progress}%</span>}
                      <span style={{ fontSize: 11, fontWeight: 700, color: b.color }}>{b.label}</span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Ranking table — updates live as candidates finish */}
            {batch.ranking.length > 0 && (
              <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px", borderBottom: "1px solid #172840" }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "#EFF6FF" }}>Ranked Candidates</span>
                  <button
                    onClick={() => exportCsv(batch.batch_id)}
                    disabled={exporting}
                    style={{ padding: "8px 16px", borderRadius: 10, border: "1px solid #172840", background: "#0A1525", color: "#CBD5E1", fontSize: 12, fontWeight: 700, cursor: exporting ? "default" : "pointer", opacity: exporting ? 0.6 : 1 }}
                  >
                    {exporting ? "Exporting…" : "⬇ Export CSV"}
                  </button>
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ textAlign: "left", fontSize: 11, color: "#64748B", textTransform: "uppercase", letterSpacing: .5 }}>
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
                        const rec = recBadge(c.recommendation);
                        return (
                          <tr key={c.report_id} style={{ borderTop: "1px solid #172840" }}>
                            <td style={{ padding: "12px 20px", fontSize: 13, fontWeight: 800, color: c.rank <= 3 ? "#FBBF24" : "#64748B" }}>#{c.rank}</td>
                            <td style={{ padding: "12px 12px", fontSize: 13, color: "#EFF6FF", fontWeight: 600 }}>{c.candidate_name}</td>
                            <td style={{ padding: "12px 12px", fontSize: 11, color: "#64748B", fontFamily: "monospace" }}>{c.file_name}</td>
                            <td style={{ padding: "12px 12px" }}>
                              <span style={{ fontSize: 14, fontWeight: 800, color: scoreColor(c.overall_score) }}>{c.overall_score}</span>
                            </td>
                            <td style={{ padding: "12px 12px" }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: rec.color, background: rec.bg, padding: "4px 10px", borderRadius: 999 }}>{rec.label}</span>
                            </td>
                            <td style={{ padding: "12px 20px" }}>
                              <Link href={`/report/${c.report_id}`} style={{ fontSize: 12, color: "#4B8DFF", textDecoration: "none", fontWeight: 700 }}>View →</Link>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {batch.is_done && (
              <div style={{ marginTop: 20, textAlign: "center" }}>
                <button onClick={reset} style={{ padding: "11px 28px", borderRadius: 12, border: "1px solid #172840", cursor: "pointer", background: "#0E1C2E", color: "#CBD5E1", fontWeight: 700, fontSize: 13, fontFamily: "inherit" }}>
                  Upload Another Batch
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── ERROR ── */}
        {state.phase === "error" && (
          <div className="animate-fade-up" style={{ textAlign: "center" }}>
            <div style={{ background: "#0E1C2E", border: "1px solid rgba(220,38,38,.3)", borderRadius: 20, padding: "44px 32px" }}>
              <div style={{ fontSize: 40, marginBottom: 16 }}>⚠</div>
              <div style={{ fontSize: 17, fontWeight: 700, color: "#EFF6FF", marginBottom: 10 }}>Bulk Upload Failed</div>
              <div style={{ fontSize: 13, color: "#94A3B8", lineHeight: 1.65, marginBottom: 28 }}>{state.message}</div>
              <button onClick={reset} style={{ padding: "11px 28px", borderRadius: 12, border: "none", cursor: "pointer", background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 14, fontFamily: "inherit" }}>
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
