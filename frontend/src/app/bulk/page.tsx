"use client";
import { useEffect, useCallback, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useBulkAnalysis } from "@/hooks/useBulkAnalysis";
import { bulkAPI, APIError } from "@/lib/api";
import type { DuplicateCheckResult } from "@/types";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";

const MAX_FILES = 50;
const MAX_MB = 10;

function scoreColor(n: number) {
  if (n >= 75) return "#10B981";
  if (n >= 55) return "#F59E0B";
  return "#EF4444";
}

export default function BulkUploadPage() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, token, logout, hasHydrated } = useAuthStore();
  const { state, upload, exportCsv, exporting, exportError, reset } = useBulkAnalysis();
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
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "36px 24px 80px" }}>
        
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 30, fontWeight: 800, color: "#F8FAFC", margin: "0 0 8px", letterSpacing: -0.7 }}>
            Bulk Candidate Upload & Ranking
          </h1>
          <p style={{ fontSize: 14, color: "#94A3B8", margin: 0 }}>
            Upload up to {MAX_FILES} resumes at once. HireLens ranks candidates by credibility and flags duplicates automatically.
          </p>
        </div>

        {/* ── Dropzone & Upload Queue ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: "2px dashed rgba(99, 102, 241, 0.4)",
                borderRadius: 24, padding: "48px 32px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 16,
                cursor: "pointer", background: "rgba(30, 41, 59, 0.5)",
                backdropFilter: "blur(16px)", textAlign: "center",
                transition: "all 0.2s ease"
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
              <div style={{ width: 68, height: 68, borderRadius: 20, background: "rgba(99, 102, 241, 0.15)", border: "1px solid rgba(99, 102, 241, 0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28 }}>
                🗂️
              </div>
              <div>
                <div style={{ fontSize: 17, fontWeight: 700, color: "#F8FAFC", marginBottom: 4 }}>Drop candidate resumes here</div>
                <div style={{ fontSize: 13, color: "#94A3B8" }}>PDF or DOCX · Max {MAX_FILES} files per batch · Under {MAX_MB}MB each</div>
              </div>
            </div>

            {pickError && (
              <div style={{ marginTop: 16, padding: "12px 16px", borderRadius: 12, background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#EF4444", fontSize: 13 }}>
                ⚠️ {pickError}
              </div>
            )}

            {/* Pending files list */}
            {pending.length > 0 && (
              <div style={{ marginTop: 24, background: "rgba(30, 41, 59, 0.6)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 20, padding: 24 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC" }}>Selected Files ({pending.length}/{MAX_FILES})</span>
                  <button onClick={startUpload} style={{ padding: "10px 24px", borderRadius: 10, background: "linear-gradient(135deg, #6366F1, #4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 13, border: "none", cursor: "pointer" }}>
                    Start Batch Analysis
                  </button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
                  {pending.map((f, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", background: "rgba(15, 23, 42, 0.6)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, fontSize: 12 }}>
                      <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 160, color: "#CBD5E1" }}>{f.name}</span>
                      <button onClick={(e) => { e.stopPropagation(); removeFile(i); }} style={{ background: "none", border: "none", color: "#EF4444", cursor: "pointer", fontSize: 14 }}>✕</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Processing / Results ── */}
        {(state.phase === "uploading" || state.phase === "processing" || state.phase === "done") && batch && (
          <div className="animate-fade-up">
            <div style={{ background: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(16px)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 20, padding: 28, marginBottom: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: "#F8FAFC", marginBottom: 4 }}>Batch Progress</div>
                  <div style={{ fontSize: 13, color: "#94A3B8" }}>{batch.complete} of {batch.total} resumes analyzed</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                  <div style={{ display: "flex", gap: 10 }}>
                    {state.phase === "done" && (
                      <>
                        <button onClick={() => checkDuplicates(batch.batch_id)} disabled={dupLoading} style={{ padding: "8px 16px", borderRadius: 10, background: "rgba(99,102,241,0.2)", border: "1px solid rgba(99,102,241,0.4)", color: "#818CF8", fontWeight: 600, fontSize: 12, cursor: "pointer" }}>
                          {dupLoading ? "Checking…" : "🔍 Check Duplicates"}
                        </button>
                        <button onClick={() => exportCsv(batch.batch_id)} disabled={exporting} style={{ padding: "8px 16px", borderRadius: 10, background: "linear-gradient(135deg,#6366F1,#4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 12, border: "none", cursor: "pointer" }}>
                          {exporting ? "Exporting…" : "⬇ Export Batch CSV"}
                        </button>
                        <button onClick={() => { reset(); setPending([]); }} style={{ padding: "8px 16px", borderRadius: 10, background: "rgba(30,41,59,0.8)", border: "1px solid rgba(255,255,255,0.1)", color: "#CBD5E1", fontSize: 12, cursor: "pointer" }}>
                          New Batch
                        </button>
                      </>
                    )}
                  </div>
                  {exportError && (
                    <div style={{ fontSize: 11, color: "#F87171" }}>{exportError}</div>
                  )}
                </div>
              </div>

              {/* Progress bar */}
              <div style={{ height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 99, overflow: "hidden" }}>
                <div style={{ height: "100%", background: "linear-gradient(90deg, #6366F1, #10B981)", width: `${batch.total ? Math.round((batch.complete / batch.total) * 100) : 0}%`, transition: "width 0.4s ease" }} />
              </div>
            </div>

            {/* Duplicate check results card */}
            {dupResult && (
              <div style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(245, 158, 11, 0.3)", borderRadius: 20, padding: 24, marginBottom: 24 }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: "#F59E0B", marginBottom: 10 }}>🔍 Duplicate Candidate Scan</div>
                {dupResult.clusters.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#10B981" }}>✓ No duplicate candidates detected in this batch.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {dupResult.clusters.map((c: any, i: number) => (
                      <div key={i} style={{ fontSize: 13, color: "#CBD5E1", background: "rgba(15,23,42,0.6)", padding: "10px 14px", borderRadius: 10 }}>
                        <span style={{ color: "#EF4444", fontWeight: 700 }}>Duplicate Group ({c.candidates.length}):</span> {c.candidates.map((x: any) => x.candidate_name).join(" & ")}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Candidate Rankings Table */}
            <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 20, overflow: "hidden" }}>
              <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.08)", fontSize: 13, fontWeight: 700, color: "#CBD5E1" }}>
                Candidate Credibility Rankings ({batch.ranking.length})
              </div>
              {batch.ranking.map((c: any, i: number) => (
                <div key={c.report_id || i} style={{ display: "flex", alignItems: "center", padding: "14px 24px", gap: 16, borderBottom: i < batch.ranking.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none" }}>
                  <div style={{ fontSize: 14, fontWeight: 800, color: "#64748B", width: 24 }}>#{i + 1}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC" }}>{c.candidate_name || "Unknown"}</div>
                    <div style={{ fontSize: 12, color: "#94A3B8", fontFamily: "var(--font-mono), monospace" }}>{c.file_name}</div>
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 900, color: scoreColor(c.overall_score), fontFamily: "var(--font-mono), monospace" }}>{c.overall_score}</div>
                  <VerdictChip verdict={verdictFromRecommendation(c.recommendation)} />
                  <Link href={`/report/${c.report_id}`} style={{ padding: "6px 14px", borderRadius: 8, background: "rgba(99,102,241,0.15)", color: "#818CF8", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
                    View Report →
                  </Link>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
