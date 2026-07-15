"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useJdMatch } from "@/hooks/useJdMatch";
import type { MatchedCandidate, MatchVerdict } from "@/types";

const MAX_FILES = 50;
const MAX_MB = 10;
const JD_MAX_MB = 5;
const JD_ALLOWED_EXT = ["pdf", "docx", "txt"];

function verdictBadge(v: MatchVerdict) {
  const m: Record<MatchVerdict, { label: string; color: string; bg: string }> = {
    strong_fit:   { label: "Strong Fit",  color: "#10B981", bg: "rgba(5,150,105,0.12)" },
    partial_fit:  { label: "Partial Fit", color: "#FBBF24", bg: "rgba(217,119,6,0.12)" },
    weak_fit:     { label: "Weak Fit",    color: "#F87171", bg: "rgba(220,38,38,0.12)" },
    unknown:      { label: "Unscored",    color: "#64748B", bg: "rgba(100,116,139,0.12)" },
  };
  return m[v] || m.unknown;
}

function matchColor(pct: number) {
  if (pct >= 75) return "#10B981";
  if (pct >= 45) return "#FBBF24";
  return "#F87171";
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

export default function JdMatchPage() {
  const router = useRouter();
  const { token } = useAuthStore();
  const { state, upload, exportCsv, exporting, reset } = useJdMatch();
  const inputRef = useRef<HTMLInputElement>(null);
  const jdInputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File[]>([]);
  const [jdMode, setJdMode] = useState<"paste" | "upload">("paste");
  const [jdText, setJdText] = useState("");
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [jdFileError, setJdFileError] = useState<string | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!token) router.replace("/login");
  }, [token, router]);

  const pickJdFile = useCallback((f: File) => {
    setJdFileError(null);
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!JD_ALLOWED_EXT.includes(ext || "")) {
      setJdFileError(`Unsupported file type — use PDF, DOCX, or TXT.`);
      return;
    }
    if (f.size > JD_MAX_MB * 1024 * 1024) {
      setJdFileError(`File too large — max ${JD_MAX_MB}MB.`);
      return;
    }
    setJdFile(f);
  }, []);

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

  const jdReady = jdMode === "paste" ? jdText.trim().length >= 30 : !!jdFile;
  const canSubmit = pending.length > 0 && jdReady;
  const startMatch = () => {
    if (!canSubmit) return;
    upload(pending, jdMode === "paste" ? { text: jdText } : { file: jdFile || undefined });
  };

  const isBusy = state.phase === "uploading" || state.phase === "processing";
  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;

  const fullReset = () => {
    reset();
    setPending([]);
    setJdText("");
    setJdFile(null);
    setJdFileError(null);
    setPickError(null);
  };

  return (
    <div style={{ minHeight: "100vh", background: "#060F1A" }}>
      <nav style={{ height: 54, borderBottom: "1px solid #172840", display: "flex", alignItems: "center", paddingInline: 24, gap: 16, position: "sticky", top: 0, background: "rgba(6,15,26,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EFF6FF", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <span style={{ color: "#172840" }}>|</span>
        <span style={{ fontSize: 13, color: "#64748B" }}>Job Description Match</span>
        <div style={{ flex: 1 }} />
        <Link href="/bulk" style={{ fontSize: 12, color: "#64748B", textDecoration: "none" }}>Bulk upload →</Link>
      </nav>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>

        {/* ── IDLE: JD + files ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 28, textAlign: "center" }}>
              <h1 style={{ fontSize: 26, fontWeight: 900, color: "#EFF6FF", margin: "0 0 8px", letterSpacing: -1 }}>
                Match Candidates to a Job Description
              </h1>
              <p style={{ fontSize: 14, color: "#94A3B8", margin: 0, lineHeight: 1.6 }}>
                Paste a JD, upload resumes, and HireLens ranks candidates by real fit —<br />
                not keyword overlap — with missing skills called out per candidate.
              </p>
            </div>

            {/* JD input */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <label style={{ fontSize: 13, fontWeight: 700, color: "#EFF6FF" }}>Job Description</label>
                <div style={{ display: "flex", gap: 4, background: "#0A1525", border: "1px solid #172840", borderRadius: 999, padding: 3 }}>
                  {(["paste", "upload"] as const).map((mode) => (
                    <button
                      key={mode}
                      onClick={() => setJdMode(mode)}
                      style={{
                        padding: "5px 14px", borderRadius: 999, border: "none", cursor: "pointer",
                        fontSize: 11, fontWeight: 700, fontFamily: "inherit",
                        background: jdMode === mode ? "#1D6AFF" : "transparent",
                        color: jdMode === mode ? "#EFF6FF" : "#64748B",
                        transition: "all .15s",
                      }}
                    >
                      {mode === "paste" ? "✎ Paste Text" : "📎 Upload File"}
                    </button>
                  ))}
                </div>
              </div>

              {jdMode === "paste" ? (
                <>
                  <textarea
                    value={jdText}
                    onChange={(e) => setJdText(e.target.value)}
                    placeholder="Paste the full job description here — responsibilities, required skills, experience level…"
                    rows={8}
                    style={{
                      width: "100%", background: "#0A1525", border: "1px solid #172840", borderRadius: 12,
                      padding: 14, fontSize: 13, color: "#EFF6FF", fontFamily: "inherit", resize: "vertical",
                      outline: "none", lineHeight: 1.6, boxSizing: "border-box",
                    }}
                  />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                    <span style={{ fontSize: 11, color: jdText.trim().length >= 30 || jdText.length === 0 ? "#64748B" : "#F87171" }}>
                      {jdText.trim().length < 30 && jdText.length > 0 ? "Add a bit more detail (min 30 characters)" : " "}
                    </span>
                    <span style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace" }}>{jdText.length}/6000</span>
                  </div>
                </>
              ) : (
                <div>
                  <input
                    ref={jdInputRef} type="file" accept=".pdf,.docx,.txt" style={{ display: "none" }}
                    onChange={(e) => { if (e.target.files?.[0]) pickJdFile(e.target.files[0]); e.target.value = ""; }}
                  />
                  {!jdFile ? (
                    <div
                      onClick={() => jdInputRef.current?.click()}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files?.[0]) pickJdFile(e.dataTransfer.files[0]); }}
                      style={{
                        border: "2px dashed #1E3450", borderRadius: 12, padding: "24px 20px",
                        display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
                        cursor: "pointer", background: "#0A1525", textAlign: "center",
                      }}
                    >
                      <span style={{ fontSize: 20 }}>📄</span>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#EFF6FF" }}>Click or drop a JD file</div>
                      <div style={{ fontSize: 11, color: "#64748B" }}>PDF, DOCX, or TXT · Max {JD_MAX_MB}MB</div>
                    </div>
                  ) : (
                    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderRadius: 12, background: "#0A1525", border: "1px solid #172840" }}>
                      <span style={{ fontSize: 16 }}>📄</span>
                      <span style={{ fontSize: 13, color: "#EFF6FF", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{jdFile.name}</span>
                      <span style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace" }}>{(jdFile.size / 1024 / 1024).toFixed(1)}MB</span>
                      <button onClick={() => setJdFile(null)} style={{ background: "none", border: "none", color: "#64748B", cursor: "pointer", fontSize: 14 }}>✕</button>
                    </div>
                  )}
                  {jdFileError && (
                    <div style={{ marginTop: 8, fontSize: 11, color: "#F87171" }}>{jdFileError}</div>
                  )}
                </div>
              )}
            </div>

            {/* Resume dropzone */}
            <label style={{ fontSize: 13, fontWeight: 700, color: "#EFF6FF", display: "block", marginBottom: 8 }}>
              Resumes to Match
            </label>
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: "2px dashed #1E3450", borderRadius: 18, padding: "32px 24px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 10,
                cursor: "pointer", background: "#0A1525", transition: "all .2s", textAlign: "center",
              }}
              onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#1D6AFF"; (e.currentTarget as HTMLElement).style.background = "rgba(29,106,255,0.06)"; }}
              onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#1E3450"; (e.currentTarget as HTMLElement).style.background = "#0A1525"; }}
            >
              <input
                ref={inputRef} type="file" accept=".pdf,.docx" multiple style={{ display: "none" }}
                onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ""; }}
              />
              <div style={{ width: 52, height: 52, borderRadius: 16, background: "rgba(29,106,255,0.12)", border: "1.5px solid rgba(29,106,255,0.35)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>📋</div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#EFF6FF", marginBottom: 4 }}>Drop resumes here, or click to browse</div>
                <div style={{ fontSize: 12, color: "#64748B" }}>PDF or DOCX · Max {MAX_MB}MB each · Up to {MAX_FILES} files</div>
              </div>
            </div>

            {pickError && (
              <div style={{ marginTop: 12, padding: "10px 14px", background: "rgba(220,38,38,0.08)", border: "1px solid rgba(220,38,38,.3)", borderRadius: 10, fontSize: 12, color: "#F87171" }}>
                {pickError}
              </div>
            )}

            {pending.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: "#EFF6FF" }}>{pending.length} resume{pending.length > 1 ? "s" : ""} selected</span>
                  <button onClick={() => setPending([])} style={{ background: "none", border: "none", color: "#64748B", fontSize: 12, cursor: "pointer" }}>Clear all</button>
                </div>
                <div style={{ maxHeight: 220, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, background: "#0E1C2E", border: "1px solid #172840", borderRadius: 12, padding: 8 }}>
                  {pending.map((f, i) => (
                    <div key={`${f.name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8, background: "#0A1525" }}>
                      <span style={{ fontSize: 14 }}>📄</span>
                      <span style={{ fontSize: 12, color: "#CBD5E1", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                      <span style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace" }}>{(f.size / 1024 / 1024).toFixed(1)}MB</span>
                      <button onClick={() => removeFile(i)} style={{ background: "none", border: "none", color: "#64748B", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>✕</button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button
              onClick={startMatch}
              disabled={!canSubmit}
              style={{
                marginTop: 20, width: "100%", padding: "13px 0", borderRadius: 12, border: "none",
                cursor: canSubmit ? "pointer" : "not-allowed",
                background: canSubmit ? "linear-gradient(135deg,#1D6AFF,#1045C8)" : "#172840",
                color: canSubmit ? "#EFF6FF" : "#64748B", fontWeight: 700, fontSize: 14, fontFamily: "inherit",
              }}
            >
              {!canSubmit
                ? (pending.length === 0 ? "Add resumes to continue" : "Add a job description to continue")
                : `Match ${pending.length} Resume${pending.length > 1 ? "s" : ""} Against JD`}
            </button>
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
            <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, padding: "20px 24px", marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: "#EFF6FF" }}>
                  {batch.is_done ? "Matching complete" : "Matching candidates against JD…"}
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

            {batch.ranking.length > 0 && (
              <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px", borderBottom: "1px solid #172840" }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "#EFF6FF" }}>Ranked by JD Match</span>
                  <button
                    onClick={() => exportCsv(batch.batch_id)}
                    disabled={exporting}
                    style={{ padding: "8px 16px", borderRadius: 10, border: "1px solid #172840", background: "#0A1525", color: "#CBD5E1", fontSize: 12, fontWeight: 700, cursor: exporting ? "default" : "pointer", opacity: exporting ? 0.6 : 1 }}
                  >
                    {exporting ? "Exporting…" : "⬇ Export CSV"}
                  </button>
                </div>

                <div>
                  {batch.ranking.map((c: MatchedCandidate) => {
                    const v = verdictBadge(c.verdict);
                    const isOpen = expanded === c.report_id;
                    return (
                      <div key={c.report_id} style={{ borderTop: "1px solid #172840", background: c.is_best_fit ? "rgba(16,185,129,0.05)" : "transparent" }}>
                        <div
                          onClick={() => setExpanded(isOpen ? null : c.report_id)}
                          style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", cursor: "pointer" }}
                        >
                          <span style={{ fontSize: 13, fontWeight: 800, color: c.rank <= 3 ? "#FBBF24" : "#64748B", width: 28 }}>#{c.rank}</span>

                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ fontSize: 13, color: "#EFF6FF", fontWeight: 700 }}>{c.candidate_name}</span>
                              {c.is_best_fit && (
                                <span style={{ fontSize: 10, fontWeight: 800, color: "#10B981", background: "rgba(5,150,105,0.15)", padding: "2px 8px", borderRadius: 999, letterSpacing: .3 }}>★ BEST FIT</span>
                              )}
                            </div>
                            <div style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace", marginTop: 2 }}>{c.file_name}</div>
                          </div>

                          <div style={{ textAlign: "right", minWidth: 70 }}>
                            <div style={{ fontSize: 18, fontWeight: 900, color: matchColor(c.match_percent) }}>{c.match_percent}%</div>
                            <span style={{ fontSize: 10, fontWeight: 700, color: v.color, background: v.bg, padding: "2px 8px", borderRadius: 999 }}>{v.label}</span>
                          </div>

                          <span style={{ fontSize: 12, color: "#64748B" }}>{isOpen ? "▲" : "▼"}</span>
                        </div>

                        {isOpen && (
                          <div style={{ padding: "0 20px 18px 62px" }}>
                            {c.rationale && (
                              <p style={{ fontSize: 12, color: "#94A3B8", lineHeight: 1.6, margin: "0 0 12px" }}>{c.rationale}</p>
                            )}
                            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                              {c.matching_skills.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ fontSize: 11, fontWeight: 700, color: "#10B981", marginBottom: 6 }}>✓ MATCHING</div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                    {c.matching_skills.map((s) => (
                                      <span key={s} style={{ fontSize: 11, color: "#A7F3D0", background: "rgba(5,150,105,0.12)", padding: "3px 9px", borderRadius: 999 }}>{s}</span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {c.missing_skills.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ fontSize: 11, fontWeight: 700, color: "#F87171", marginBottom: 6 }}>✕ MISSING</div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                    {c.missing_skills.map((s) => (
                                      <span key={s} style={{ fontSize: 11, color: "#FECACA", background: "rgba(220,38,38,0.12)", padding: "3px 9px", borderRadius: 999 }}>{s}</span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                            <Link href={`/report/${c.report_id}`} style={{ display: "inline-block", marginTop: 14, fontSize: 12, color: "#4B8DFF", textDecoration: "none", fontWeight: 700 }}>
                              View full credibility report →
                            </Link>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {batch.is_done && (
              <div style={{ marginTop: 20, textAlign: "center" }}>
                <button onClick={fullReset} style={{ padding: "11px 28px", borderRadius: 12, border: "1px solid #172840", cursor: "pointer", background: "#0E1C2E", color: "#CBD5E1", fontWeight: 700, fontSize: 13, fontFamily: "inherit" }}>
                  Match Another Batch
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
              <div style={{ fontSize: 17, fontWeight: 700, color: "#EFF6FF", marginBottom: 10 }}>JD Match Failed</div>
              <div style={{ fontSize: 13, color: "#94A3B8", lineHeight: 1.65, marginBottom: 28 }}>{state.message}</div>
              <button onClick={fullReset} style={{ padding: "11px 28px", borderRadius: 12, border: "none", cursor: "pointer", background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 14, fontFamily: "inherit" }}>
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
