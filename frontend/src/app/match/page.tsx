"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useJdMatch } from "@/hooks/useJdMatch";
import {
  Search,
  Target,
  FileText,
  AlertCircle,
  Check,
  X,
  Download,
} from "lucide-react";
import type { MatchVerdict, MatchedCandidate } from "@/types";
import { color, radius } from "@/lib/design-tokens";
import { Card, Button, TextInput, PageShell } from "@/components/ui/primitives";
import { AppNavbar } from "@/components/ui/AppNavbar";

const MAX_FILES = 50;
const MAX_MB = 10;
const JD_MAX_MB = 5;

function verdictBadge(v: MatchVerdict) {
  const m: Record<MatchVerdict, { label: string; color: string; bg: string; border: string }> = {
    strong_fit:   { label: "Strong Fit",  color: color.success, bg: color.successBg, border: color.successBorder },
    partial_fit:  { label: "Partial Fit", color: color.warning, bg: color.warningBg, border: color.warningBorder },
    weak_fit:     { label: "Weak Fit",    color: color.danger,  bg: color.dangerBg,  border: color.dangerBorder },
    unknown:      { label: "Unscored",    color: color.textMuted, bg: "rgba(148,163,184,0.12)", border: "rgba(148,163,184,0.3)" },
  };
  return m[v] || m.unknown;
}

function matchColor(pct: number) {
  if (pct >= 75) return color.success;
  if (pct >= 45) return color.warning;
  return color.danger;
}

export default function JdMatchPage() {
  const router = useRouter();
  const { token, sessionChecked } = useAuthStore();
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
    if (sessionChecked && !token) router.replace("/login");
  }, [sessionChecked, token, router]);

  const pickJdFile = useCallback((f: File) => {
    setJdFileError(null);
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!["pdf", "docx", "txt"].includes(ext || "")) {
      setJdFileError("Unsupported file type — use PDF, DOCX, or TXT.");
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

    for (const f of arr) {
      const ext = f.name.split(".").pop()?.toLowerCase();
      if (!["pdf", "docx"].includes(ext || "")) continue;
      if (f.size > MAX_MB * 1024 * 1024) continue;
      valid.push(f);
    }

    setPending((prev) => {
      const combined = [...prev, ...valid];
      if (combined.length > MAX_FILES) {
        setPickError(`Max ${MAX_FILES} files per batch.`);
        return combined.slice(0, MAX_FILES);
      }
      return combined;
    });
  }, []);

  const startAnalysis = () => {
    if (pending.length === 0) return;
    if (jdMode === "paste" && !jdText.trim()) { setPickError("Please paste a Job Description."); return; }
    if (jdMode === "upload" && !jdFile) { setPickError("Please upload a Job Description file."); return; }

    upload(
      pending,
      {
        text: jdMode === "paste" ? jdText : undefined,
        file: jdMode === "upload" && jdFile ? jdFile : undefined,
      }
    );
  };

  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;

  return (
    <PageShell>
      <AppNavbar />

      {/* Main Container */}
      <div style={{ maxWidth: 1120, margin: "0 auto", padding: "36px 24px 80px" }}>

        <div style={{ marginBottom: 32 }}>
          <h1 className="font-display" style={{ fontSize: 28, fontWeight: 600, color: color.textPrimary, margin: "0 0 8px" }}>
            Job Description Match & Ranking
          </h1>
          <p style={{ fontSize: 14, color: color.textMuted, margin: 0 }}>
            Compare candidate resumes directly against your Job Description (JD) to evaluate skill fit and role alignment.
          </p>
        </div>

        {state.phase === "idle" && (
          <div className="animate-fade-up" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>

            {/* Left: Job Description Input */}
            <Card style={{ padding: 28 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <span style={{ fontSize: 16, fontWeight: 600, color: color.textPrimary }}>1. Job Description</span>
                <div style={{ display: "flex", gap: 6, background: "rgba(15,23,42,0.6)", padding: 3, borderRadius: radius.sm }}>
                  <button onClick={() => setJdMode("paste")} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: jdMode === "paste" ? color.brand : "transparent", color: jdMode === "paste" ? "#FFF" : color.textMuted, border: "none", cursor: "pointer" }}>Paste Text</button>
                  <button onClick={() => setJdMode("upload")} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: jdMode === "upload" ? color.brand : "transparent", color: jdMode === "upload" ? "#FFF" : color.textMuted, border: "none", cursor: "pointer" }}>Upload File</button>
                </div>
              </div>

              {jdMode === "paste" ? (
                <textarea
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  placeholder="Paste job description text here (requirements, responsibilities, required skills)…"
                  style={{ width: "100%", height: 260, boxSizing: "border-box", padding: 14, background: color.bgAlt, border: `1px solid ${color.border}`, borderRadius: radius.md, color: color.textPrimary, fontSize: 13, outline: "none", resize: "vertical" }}
                />
              ) : (
                <div onClick={() => jdInputRef.current?.click()} style={{ border: `1.5px dashed ${color.border}`, borderRadius: radius.lg, padding: "44px 24px", textAlign: "center", cursor: "pointer", background: color.bgAlt }}>
                  <input ref={jdInputRef} type="file" accept=".pdf,.docx,.txt" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; if (f) pickJdFile(f); }} />
                  <div style={{ display: "flex", justifyContent: "center", marginBottom: 8 }}>
                    <FileText size={28} color={color.brandLight} />
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>{jdFile ? jdFile.name : "Upload JD document"}</div>
                  <div style={{ fontSize: 12, color: color.textMuted, marginTop: 4 }}>PDF, DOCX, or TXT up to {JD_MAX_MB}MB</div>
                  {jdFileError && <div style={{ fontSize: 12, color: color.danger, marginTop: 8 }}>{jdFileError}</div>}
                </div>
              )}
            </Card>

            {/* Right: Resumes Dropzone */}
            <Card style={{ padding: 28, display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 16, fontWeight: 600, color: color.textPrimary, marginBottom: 16 }}>2. Candidate Resumes</span>

              <div onClick={() => inputRef.current?.click()} style={{ border: `1.5px dashed ${color.border}`, borderRadius: radius.lg, padding: "34px 24px", textAlign: "center", cursor: "pointer", background: color.bgAlt, marginBottom: 16 }}>
                <input ref={inputRef} type="file" multiple accept=".pdf,.docx" style={{ display: "none" }} onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); }} />
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 8 }}>
                  <Target size={28} color={color.brandLight} />
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>Drop resumes to match</div>
                <div style={{ fontSize: 12, color: color.textMuted, marginTop: 4 }}>PDF or DOCX up to {MAX_FILES} files</div>
              </div>

              {pending.length > 0 && (
                <div style={{ flex: 1, marginBottom: 16 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: color.textSecondary, marginBottom: 8 }}>Resumes Selected ({pending.length})</div>
                  <div style={{ maxHeight: 120, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                    {pending.map((f, i) => (
                      <div key={i} style={{ fontSize: 12, color: color.textMuted, background: "rgba(15,23,42,0.6)", padding: "6px 10px", borderRadius: 6 }}>
                        {f.name}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {pickError && (
                <div style={{ fontSize: 12, color: color.danger, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
                  <AlertCircle size={14} style={{ flexShrink: 0 }} />
                  <span>{pickError}</span>
                </div>
              )}

              <Button onClick={startAnalysis} disabled={pending.length === 0} style={{ width: "100%", padding: "12px 24px" }}>
                Run JD Match Analysis
              </Button>
            </Card>

          </div>
        )}

        {/* ── Results ── */}
        {(state.phase === "uploading" || state.phase === "processing" || state.phase === "done") && batch && (
          <div className="animate-fade-up">
            <Card style={{ padding: 28, marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>JD Match Completed</div>
                <div style={{ fontSize: 13, color: color.textMuted }}>{batch.complete} of {batch.total} candidates evaluated</div>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <Button onClick={() => exportCsv(batch.batch_id)} disabled={exporting}>
                  <Download size={14} />
                  <span>{exporting ? "Exporting…" : "Export Match CSV"}</span>
                </Button>
                <Button variant="secondary" onClick={() => { reset(); setPending([]); setJdText(""); setJdFile(null); }}>
                  New JD Match
                </Button>
              </div>
            </Card>

            {/* Candidates Fit Table */}
            <Card style={{ overflow: "hidden" }}>
              <div style={{ padding: "16px 24px", borderBottom: `1px solid ${color.border}`, fontSize: 13, fontWeight: 600, color: color.textSecondary }}>
                Candidate Match Rankings ({batch.ranking.length})
              </div>
              {batch.ranking.map((c: MatchedCandidate, i: number) => {
                const badge = verdictBadge(c.verdict);
                return (
                  <div key={c.report_id || i} style={{ padding: "18px 24px", borderBottom: i < batch.ranking.length - 1 ? `1px solid ${color.borderSubtle}` : "none" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: color.textFaint, width: 24 }}>#{i + 1}</div>
                      <div style={{ flex: 1, minWidth: 140 }}>
                        <div style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary }}>{c.candidate_name || "Unknown Candidate"}</div>
                        <div style={{ fontSize: 12, color: color.textMuted, fontFamily: "var(--font-mono), monospace" }}>{c.file_name}</div>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 11, color: color.textMuted }}>Match Score</span>
                        <span style={{ fontSize: 20, fontWeight: 600, color: matchColor(c.match_percent), fontFamily: "var(--font-mono), monospace" }}>{c.match_percent}%</span>
                      </div>

                      <span style={{ padding: "4px 12px", borderRadius: radius.pill, background: badge.bg, border: `1px solid ${badge.border}`, color: badge.color, fontSize: 11, fontWeight: 600 }}>
                        {badge.label}
                      </span>

                      <button onClick={() => setExpanded(expanded === c.report_id ? null : c.report_id)} style={{ padding: "6px 14px", borderRadius: radius.sm, background: color.surfaceRaised, color: color.brandLight, fontSize: 12, fontWeight: 600, border: `1px solid ${color.border}`, cursor: "pointer" }}>
                        {expanded === c.report_id ? "Hide Skills" : "View Breakdown"}
                      </button>
                    </div>

                    {expanded === c.report_id && (
                      <div style={{ marginTop: 16, paddingTop: 16, borderTop: `1px solid ${color.borderSubtle}`, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: color.success, marginBottom: 8 }}>Matching Skills ({(c.matching_skills || []).length})</div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {(c.matching_skills || []).map((s, idx) => (
                              <span key={idx} style={{ padding: "3px 10px", borderRadius: 6, background: color.successBg, color: color.success, fontSize: 11, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}>
                                <Check size={11} strokeWidth={3} />
                                <span>{s}</span>
                              </span>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: color.danger, marginBottom: 8 }}>Missing Skills ({(c.missing_skills || []).length})</div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {(c.missing_skills || []).map((s, idx) => (
                              <span key={idx} style={{ padding: "3px 10px", borderRadius: 6, background: color.dangerBg, color: color.danger, fontSize: 11, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}>
                                <X size={11} strokeWidth={3} />
                                <span>{s}</span>
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </Card>
          </div>
        )}
      </div>
    </PageShell>
  );
}
