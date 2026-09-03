"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useJdMatch } from "@/hooks/useJdMatch";
import type { MatchVerdict } from "@/types";

const MAX_FILES = 50;
const MAX_MB = 10;
const JD_MAX_MB = 5;

function verdictBadge(v: MatchVerdict) {
  const m: Record<MatchVerdict, { label: string; color: string; bg: string; border: string }> = {
    strong_fit:   { label: "Strong Fit",  color: "#10B981", bg: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.3)" },
    partial_fit:  { label: "Partial Fit", color: "#F59E0B", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.3)" },
    weak_fit:     { label: "Weak Fit",    color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.3)" },
    unknown:      { label: "Unscored",    color: "#94A3B8", bg: "rgba(148,163,184,0.12)",border: "rgba(148,163,184,0.3)" },
  };
  return m[v] || m.unknown;
}

function matchColor(pct: number) {
  if (pct >= 75) return "#10B981";
  if (pct >= 45) return "#F59E0B";
  return "#EF4444";
}

export default function JdMatchPage() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, token, logout, hasHydrated } = useAuthStore();
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
    if (hasHydrated && !token) router.replace("/login");
  }, [hasHydrated, token, router]);

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

  const isBusy = state.phase === "uploading" || state.phase === "processing";
  const batch = state.phase === "processing" || state.phase === "done" ? state.batch : null;

  const NAV_LINKS = [
    { href: "/dashboard", label: "Dashboard", icon: "📊" },
    { href: "/analyze", label: "Analyze", icon: "⚡" },
    { href: "/bulk", label: "Bulk Upload", icon: "🗂️" },
    { href: "/match", label: "JD Match", icon: "🎯" },
    { href: "/teams", label: "Teams", icon: "👥" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#0B0F17", color: "#F8FAFC" }}>
      {/* Navbar */}
      <nav style={{
        height: 64, borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        display: "flex", alignItems: "center", paddingInline: 28, gap: 24,
        position: "sticky", top: 0, background: "rgba(11, 15, 23, 0.85)",
        backdropFilter: "blur(16px)", zIndex: 100
      }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
          <div style={{
            width: 32, height: 32, borderRadius: 10,
            background: "linear-gradient(135deg, #6366F1, #8B5CF6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16, boxShadow: "0 0 16px rgba(99,102,241,0.4)"
          }}>🔎</div>
          <span style={{ fontWeight: 800, fontSize: 18, color: "#F8FAFC", letterSpacing: -0.5 }}>HireLens</span>
        </Link>

        {/* Tab Pills */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: "rgba(30, 41, 59, 0.5)", padding: 4, borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)" }}>
          {NAV_LINKS.map(link => {
            const active = pathname === link.href;
            return (
              <Link key={link.href} href={link.href} style={{
                padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                color: active ? "#F8FAFC" : "#94A3B8",
                background: active ? "rgba(99, 102, 241, 0.25)" : "transparent",
                border: active ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid transparent",
                textDecoration: "none", transition: "all 0.15s ease",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <span>{link.icon}</span>
                <span>{link.label}</span>
              </Link>
            );
          })}
        </div>

        <div style={{ flex: 1 }} />

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", borderRadius: 99, background: "rgba(30,41,59,0.6)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ width: 22, height: 22, borderRadius: "50%", background: "#6366F1", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>
              {user?.full_name ? user.full_name[0].toUpperCase() : "U"}
            </div>
            <span style={{ fontSize: 12, color: "#CBD5E1", fontWeight: 500 }}>{user?.email}</span>
          </div>
          <button onClick={() => { logout(); router.replace("/login"); }}
            style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(30,41,59,0.4)", color: "#94A3B8", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
            Sign Out
          </button>
        </div>
      </nav>

      {/* Main Container */}
      <div style={{ maxWidth: 1120, margin: "0 auto", padding: "36px 24px 80px" }}>
        
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 30, fontWeight: 800, color: "#F8FAFC", margin: "0 0 8px", letterSpacing: -0.7 }}>
            Job Description Match & Ranking
          </h1>
          <p style={{ fontSize: 14, color: "#94A3B8", margin: 0 }}>
            Compare candidate resumes directly against your Job Description (JD) to evaluate skill fit and role alignment.
          </p>
        </div>

        {state.phase === "idle" && (
          <div className="animate-fade-up" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
            
            {/* Left: Job Description Input */}
            <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 20, padding: 28 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#F8FAFC" }}>1. Job Description</span>
                <div style={{ display: "flex", gap: 6, background: "rgba(15,23,42,0.6)", padding: 3, borderRadius: 8 }}>
                  <button onClick={() => setJdMode("paste")} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: jdMode === "paste" ? "#6366F1" : "transparent", color: jdMode === "paste" ? "#FFF" : "#94A3B8", border: "none", cursor: "pointer" }}>Paste Text</button>
                  <button onClick={() => setJdMode("upload")} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: jdMode === "upload" ? "#6366F1" : "transparent", color: jdMode === "upload" ? "#FFF" : "#94A3B8", border: "none", cursor: "pointer" }}>Upload File</button>
                </div>
              </div>

              {jdMode === "paste" ? (
                <textarea
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  placeholder="Paste job description text here (requirements, responsibilities, required skills)…"
                  style={{ width: "100%", height: 260, boxSizing: "border-box", padding: 14, background: "rgba(15, 23, 42, 0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, color: "#F8FAFC", fontSize: 13, outline: "none", resize: "vertical" }}
                />
              ) : (
                <div onClick={() => jdInputRef.current?.click()} style={{ border: "2px dashed rgba(99,102,241,0.4)", borderRadius: 16, padding: "48px 24px", textAlign: "center", cursor: "pointer", background: "rgba(15, 23, 42, 0.5)" }}>
                  <input ref={jdInputRef} type="file" accept=".pdf,.docx,.txt" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; if (f) pickJdFile(f); }} />
                  <div style={{ fontSize: 28, marginBottom: 8 }}>📄</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC" }}>{jdFile ? jdFile.name : "Upload JD document"}</div>
                  <div style={{ fontSize: 12, color: "#94A3B8", marginTop: 4 }}>PDF, DOCX, or TXT up to {JD_MAX_MB}MB</div>
                  {jdFileError && <div style={{ fontSize: 12, color: "#EF4444", marginTop: 8 }}>{jdFileError}</div>}
                </div>
              )}
            </div>

            {/* Right: Resumes Dropzone */}
            <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 20, padding: 28, display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#F8FAFC", marginBottom: 16 }}>2. Candidate Resumes</span>
              
              <div onClick={() => inputRef.current?.click()} style={{ border: "2px dashed rgba(99,102,241,0.4)", borderRadius: 16, padding: "36px 24px", textAlign: "center", cursor: "pointer", background: "rgba(15, 23, 42, 0.5)", marginBottom: 16 }}>
                <input ref={inputRef} type="file" multiple accept=".pdf,.docx" style={{ display: "none" }} onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); }} />
                <div style={{ fontSize: 28, marginBottom: 8 }}>🎯</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC" }}>Drop resumes to match</div>
                <div style={{ fontSize: 12, color: "#94A3B8", marginTop: 4 }}>PDF or DOCX up to {MAX_FILES} files</div>
              </div>

              {pending.length > 0 && (
                <div style={{ flex: 1, marginBottom: 16 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#CBD5E1", marginBottom: 8 }}>Resumes Selected ({pending.length})</div>
                  <div style={{ maxHeight: 120, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                    {pending.map((f, i) => (
                      <div key={i} style={{ fontSize: 12, color: "#94A3B8", background: "rgba(15,23,42,0.6)", padding: "6px 10px", borderRadius: 6 }}>
                        {f.name}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {pickError && <div style={{ fontSize: 12, color: "#EF4444", marginBottom: 12 }}>⚠️ {pickError}</div>}

              <button onClick={startAnalysis} disabled={pending.length === 0} style={{ width: "100%", padding: "12px 24px", borderRadius: 12, background: "linear-gradient(135deg,#6366F1,#4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 14, border: "none", cursor: pending.length ? "pointer" : "default", opacity: pending.length ? 1 : 0.5 }}>
                Run JD Match Analysis
              </button>
            </div>

          </div>
        )}

        {/* ── Results ── */}
        {(state.phase === "uploading" || state.phase === "processing" || state.phase === "done") && batch && (
          <div className="animate-fade-up">
            <div style={{ background: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(16px)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 20, padding: 28, marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 700, color: "#F8FAFC", marginBottom: 4 }}>JD Match Completed</div>
                <div style={{ fontSize: 13, color: "#94A3B8" }}>{batch.complete} of {batch.total} candidates evaluated</div>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <button onClick={() => exportCsv(batch.batch_id)} disabled={exporting} style={{ padding: "10px 20px", borderRadius: 10, background: "linear-gradient(135deg,#6366F1,#4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 13, border: "none", cursor: "pointer" }}>
                  {exporting ? "Exporting…" : "⬇ Export Match CSV"}
                </button>
                <button onClick={() => { reset(); setPending([]); setJdText(""); setJdFile(null); }} style={{ padding: "10px 20px", borderRadius: 10, background: "rgba(30,41,59,0.8)", border: "1px solid rgba(255,255,255,0.1)", color: "#CBD5E1", fontSize: 13, cursor: "pointer" }}>
                  New JD Match
                </button>
              </div>
            </div>

            {/* Candidates Fit Table */}
            <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 20, overflow: "hidden" }}>
              <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.08)", fontSize: 13, fontWeight: 700, color: "#CBD5E1" }}>
                Candidate Match Rankings ({batch.ranking.length})
              </div>
              {batch.ranking.map((c: any, i: number) => {
                const badge = verdictBadge(c.verdict);
                return (
                  <div key={c.report_id || i} style={{ padding: "18px 24px", borderBottom: i < batch.ranking.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                      <div style={{ fontSize: 14, fontWeight: 800, color: "#64748B", width: 24 }}>#{i + 1}</div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 700, color: "#F8FAFC" }}>{c.candidate_name || "Unknown Candidate"}</div>
                        <div style={{ fontSize: 12, color: "#94A3B8", fontFamily: "var(--font-mono), monospace" }}>{c.file_name}</div>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 11, color: "#94A3B8" }}>Match Score</span>
                        <span style={{ fontSize: 20, fontWeight: 900, color: matchColor(c.match_score), fontFamily: "var(--font-mono), monospace" }}>{c.match_score}%</span>
                      </div>

                      <span style={{ padding: "4px 12px", borderRadius: 99, background: badge.bg, border: `1px solid ${badge.border}`, color: badge.color, fontSize: 11, fontWeight: 700 }}>
                        {badge.label}
                      </span>

                      <button onClick={() => setExpanded(expanded === c.report_id ? null : c.report_id)} style={{ padding: "6px 14px", borderRadius: 8, background: "rgba(99,102,241,0.15)", color: "#818CF8", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer" }}>
                        {expanded === c.report_id ? "Hide Skills" : "View Breakdown"}
                      </button>
                    </div>

                    {expanded === c.report_id && (
                      <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid rgba(255,255,255,0.06)", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: "#10B981", marginBottom: 8 }}>Matching Skills ({(c.matching_skills || []).length})</div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {(c.matching_skills || []).map((s: string, idx: number) => (
                              <span key={idx} style={{ padding: "3px 10px", borderRadius: 6, background: "rgba(16,185,129,0.15)", color: "#10B981", fontSize: 11, fontWeight: 600 }}>
                                ✓ {s}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: "#EF4444", marginBottom: 8 }}>Missing Skills ({(c.missing_skills || []).length})</div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {(c.missing_skills || []).map((s: string, idx: number) => (
                              <span key={idx} style={{ padding: "3px 10px", borderRadius: 6, background: "rgba(239,68,68,0.15)", color: "#EF4444", fontSize: 11, fontWeight: 600 }}>
                                ✕ {s}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
