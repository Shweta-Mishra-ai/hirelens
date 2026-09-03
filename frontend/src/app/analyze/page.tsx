"use client";
import { useEffect, useCallback, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useAnalysis } from "@/hooks/useAnalysis";

const STAGES = [
  { key: "queued",     label: "Preparing document upload" },
  { key: "parsing",   label: "Extracting raw document text & structure" },
  { key: "extracting", label: "Parsing work history, skills & timeline" },
  { key: "analyzing", label: "Running Deep Decision Intelligence Analysis" },
  { key: "complete",  label: "Building report" },
];

export default function AnalyzePage() {
  const router   = useRouter();
  const pathname = usePathname();
  const { user, token, logout, hasHydrated } = useAuthStore();
  const { state, analyze, reset } = useAnalysis();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (hasHydrated && !token) router.replace("/login");
  }, [hasHydrated, token, router]);

  useEffect(() => {
    if (state.phase === "complete" && state.report?.id) {
      router.push(`/report/${state.report.id}`);
    }
  }, [state, router]);

  const handleFile = useCallback(
    (file: File) => {
      if (!file) return;
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (!["pdf", "docx"].includes(ext || "")) {
        alert("Only PDF and DOCX files are supported.");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        alert("File must be under 10MB.");
        return;
      }
      analyze(file);
    },
    [analyze],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const stageIdx = state.phase === "analyzing"
    ? STAGES.findIndex(s => s.key === state.job.stage)
    : state.phase === "complete" ? STAGES.length - 1 : 0;

  const progress = state.phase === "analyzing" ? state.job.progress : state.phase === "complete" ? 100 : 0;

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
      <div style={{ maxWidth: 680, margin: "0 auto", padding: "48px 24px" }}>

        {/* ── IDLE: Upload form ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 32, textAlign: "center" }}>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: "#F8FAFC", margin: "0 0 12px", letterSpacing: -0.8 }}>
                Analyze Candidate Resume
              </h1>
              <p style={{ fontSize: 15, color: "#94A3B8", margin: 0, lineHeight: 1.6 }}>
                Upload a real PDF or DOCX file. HireLens parses the actual content<br />
                and returns a deep credibility assessment in under 30 seconds.
              </p>
            </div>

            {/* Glassmorphic Drop zone */}
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: "2px dashed rgba(99, 102, 241, 0.4)",
                borderRadius: 24, padding: "56px 36px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 20,
                cursor: "pointer", background: "rgba(30, 41, 59, 0.5)",
                backdropFilter: "blur(16px)",
                transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)", textAlign: "center",
                boxShadow: "0 8px 32px -8px rgba(0,0,0,0.5)",
              }}
              onMouseOver={e => {
                (e.currentTarget as HTMLElement).style.borderColor = "#6366F1";
                (e.currentTarget as HTMLElement).style.background = "rgba(99, 102, 241, 0.1)";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 12px 40px -8px rgba(99,102,241,0.25)";
              }}
              onMouseOut={e => {
                (e.currentTarget as HTMLElement).style.borderColor = "rgba(99, 102, 241, 0.4)";
                (e.currentTarget as HTMLElement).style.background = "rgba(30, 41, 59, 0.5)";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 8px 32px -8px rgba(0,0,0,0.5)";
              }}
            >
              <input ref={inputRef} type="file" accept=".pdf,.docx" style={{ display: "none" }} onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
              
              <div style={{
                width: 76, height: 76, borderRadius: 24,
                background: "linear-gradient(135deg, rgba(99,102,241,0.2), rgba(139,92,246,0.2))",
                border: "1.5px solid rgba(99,102,241,0.4)",
                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 32,
                boxShadow: "0 0 24px rgba(99,102,241,0.25)"
              }}>📄</div>

              <div>
                <div style={{ fontSize: 18, fontWeight: 700, color: "#F8FAFC", marginBottom: 6 }}>Drop resume file here</div>
                <div style={{ fontSize: 13, color: "#94A3B8" }}>Supports PDF or DOCX · Max 10MB</div>
              </div>

              <div style={{
                padding: "12px 32px", borderRadius: 12,
                background: "linear-gradient(135deg, #6366F1, #4F46E5)",
                color: "#FFFFFF", fontWeight: 700, fontSize: 14,
                boxShadow: "0 4px 16px rgba(99,102,241,0.35)"
              }}>
                Choose Resume File
              </div>
            </div>

            {/* Feature Cards Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 24 }}>
              {[
                ["⚡", "Deep Decision Engine", "Frontier-class semantic intelligence"],
                ["📊", "Credibility Score", "Evidence-linked 0–100 rating"],
                ["🚩", "Risk Flags", "Cites exact candidate text"],
                ["💬", "Custom Interview Qs", "Targeted probe questions"],
              ].map(([icon, title, desc]) => (
                <div key={title as string} style={{
                  padding: "16px 18px", background: "rgba(30, 41, 59, 0.6)",
                  border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 16
                }}>
                  <div style={{ fontSize: 20, marginBottom: 6 }}>{icon}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#F8FAFC", marginBottom: 2 }}>{title}</div>
                  <div style={{ fontSize: 12, color: "#94A3B8" }}>{desc}</div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 20, padding: "14px 18px", background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.06)", borderRadius: 14, fontSize: 12, color: "#94A3B8", lineHeight: 1.6 }}>
              🛡️ <strong style={{ color: "#CBD5E1" }}>Privacy & Compliance Notice:</strong> Resume data is processed securely and protected under enterprise encryption standards.
            </div>
          </div>
        )}

        {/* ── UPLOADING ── */}
        {state.phase === "uploading" && (
          <div className="animate-fade-up" style={{ textAlign: "center", padding: "48px 0" }}>
            <div style={{ width: 60, height: 60, border: "4px solid rgba(255,255,255,0.1)", borderTopColor: "#6366F1", borderRadius: "50%", margin: "0 auto 24px" }} className="animate-spin" />
            <div style={{ fontSize: 18, fontWeight: 700, color: "#F8FAFC", marginBottom: 6 }}>Uploading resume…</div>
            <div style={{ fontSize: 14, color: "#94A3B8" }}>Sending to HireLens API</div>
          </div>
        )}

        {/* ── ANALYZING ── */}
        {state.phase === "analyzing" && (
          <div className="animate-fade-up">
            <div style={{
              background: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(16px)",
              border: "1px solid rgba(99, 102, 241, 0.3)", borderRadius: 24, padding: "36px 40px",
              boxShadow: "0 12px 40px -10px rgba(0,0,0,0.6)"
            }}>
              <div style={{ marginBottom: 28 }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: "#F8FAFC", marginBottom: 4 }}>Analyzing Candidate Resume</div>
                <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 12, color: "#818CF8" }}>{state.job.file_name}</div>
              </div>

              {/* Live status bar */}
              <div style={{ padding: "14px 18px", background: "rgba(15, 23, 42, 0.6)", border: "1px solid rgba(99, 102, 241, 0.3)", borderRadius: 14, marginBottom: 28, display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ display: "flex", gap: 4 }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{ width: 7, height: 7, borderRadius: "50%", background: "#6366F1", animation: `pulse-dot ${1.1 + i * 0.15}s ${i * 0.15}s ease-in-out infinite` }} />
                  ))}
                </div>
                <span style={{ fontSize: 14, color: "#F8FAFC", fontWeight: 600 }}>
                  {STAGES.find(s => s.key === state.job.stage)?.label || state.job.stage}
                </span>
                <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono), monospace", fontSize: 13, color: "#818CF8", fontWeight: 700 }}>{progress}%</span>
              </div>

              {/* Stage Steps */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {STAGES.map((s, i) => {
                  const done   = i < stageIdx;
                  const active = i === stageIdx;
                  return (
                    <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{
                        width: 26, height: 26, borderRadius: 8, flexShrink: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: done ? "rgba(16, 185, 129, 0.15)" : active ? "rgba(99, 102, 241, 0.2)" : "transparent",
                        border: `1.5px solid ${done ? "#10B981" : active ? "#6366F1" : "rgba(255,255,255,0.1)"}`,
                        fontSize: 12, transition: "all 0.3s",
                      }}>
                        {done ? <span style={{ color: "#10B981", fontWeight: 800 }}>✓</span>
                               : <span style={{ color: active ? "#818CF8" : "#64748B" }}>{i + 1}</span>}
                      </div>
                      <span style={{ fontSize: 13, color: done ? "#10B981" : active ? "#F8FAFC" : "#64748B", fontWeight: active ? 600 : 400 }}>
                        {s.label}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Progress bar */}
              <div style={{ marginTop: 28, height: 4, background: "rgba(255,255,255,0.08)", borderRadius: 99 }}>
                <div style={{ height: "100%", background: "linear-gradient(90deg, #6366F1, #8B5CF6)", borderRadius: 99, width: `${Math.max(5, progress)}%`, transition: "width 0.6s ease" }} />
              </div>
            </div>
          </div>
        )}

        {/* ── ERROR ── */}
        {state.phase === "error" && (
          <div className="animate-fade-up" style={{ textAlign: "center" }}>
            <div style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(239, 68, 68, 0.4)", borderRadius: 24, padding: "48px 36px" }}>
              <div style={{ fontSize: 44, marginBottom: 16 }}>⚠️</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#F8FAFC", marginBottom: 10 }}>Analysis Failed</div>
              <div style={{ fontSize: 14, color: "#94A3B8", lineHeight: 1.6, marginBottom: 28 }}>{state.message}</div>
              <button onClick={reset} style={{ padding: "12px 32px", borderRadius: 12, border: "none", cursor: "pointer", background: "linear-gradient(135deg, #6366F1, #4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 14 }}>
                Try Again
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
