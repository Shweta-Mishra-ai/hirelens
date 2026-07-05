"use client";
import { useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useAnalysis } from "@/hooks/useAnalysis";

const STAGES = [
  { key: "queued",     label: "Preparing upload" },
  { key: "parsing",   label: "Extracting document text" },
  { key: "extracting", label: "Parsing resume structure" },
  { key: "analyzing", label: "Running Deep Decision Intelligence Analysis" },
  { key: "complete",  label: "Building your report" },
];

export default function AnalyzePage() {
  const router   = useRouter();
  const { token } = useAuthStore();
  const { state, analyze, reset } = useAnalysis();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!token) router.replace("/login");
  }, [token, router]);

  // Auto-navigate when complete
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

  return (
    <div style={{ minHeight: "100vh", background: "#060F1A" }}>
      {/* Navbar */}
      <nav style={{ height: 54, borderBottom: "1px solid #172840", display: "flex", alignItems: "center", paddingInline: 24, gap: 16, position: "sticky", top: 0, background: "rgba(6,15,26,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EFF6FF", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <span style={{ color: "#172840" }}>|</span>
        <span style={{ fontSize: 13, color: "#64748B" }}>New Analysis</span>
      </nav>

      <div style={{ maxWidth: 640, margin: "0 auto", padding: "48px 24px" }}>

        {/* ── IDLE: Upload form ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 36, textAlign: "center" }}>
              <h1 style={{ fontSize: 28, fontWeight: 900, color: "#EFF6FF", margin: "0 0 10px", letterSpacing: -1 }}>
                Analyze a Resume
              </h1>
              <p style={{ fontSize: 14, color: "#94A3B8", margin: 0, lineHeight: 1.65 }}>
                Upload a real PDF or DOCX. HireLens reads the actual file<br />
                and returns a full credibility assessment in under 30 seconds.
              </p>
            </div>

            {/* Drop zone */}
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: "2px dashed #1E3450",
                borderRadius: 20, padding: "56px 32px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 18,
                cursor: "pointer", background: "#0A1525", transition: "all .2s", textAlign: "center",
              }}
              onMouseOver={e => { (e.currentTarget as HTMLElement).style.borderColor = "#1D6AFF"; (e.currentTarget as HTMLElement).style.background = "rgba(29,106,255,0.06)"; }}
              onMouseOut={e => { (e.currentTarget as HTMLElement).style.borderColor = "#1E3450"; (e.currentTarget as HTMLElement).style.background = "#0A1525"; }}
            >
              <input ref={inputRef} type="file" accept=".pdf,.docx" style={{ display: "none" }} onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
              <div style={{ width: 72, height: 72, borderRadius: 22, background: "rgba(29,106,255,0.12)", border: "1.5px solid rgba(29,106,255,0.35)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 30 }}>📄</div>
              <div>
                <div style={{ fontSize: 17, fontWeight: 700, color: "#EFF6FF", marginBottom: 6 }}>Drop resume here</div>
                <div style={{ fontSize: 13, color: "#64748B" }}>PDF or DOCX · Max 10MB</div>
              </div>
              <div style={{ padding: "11px 28px", borderRadius: 12, background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 14 }}>
                Choose File
              </div>
            </div>

            {/* Feature chips */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 20 }}>
              {[
                ["⚡", "Deep Analysis", "Frontier-class semantic engine"],
                ["📊", "Credibility Score", "Evidence-linked 0–100"],
                ["🚩", "Risk Flags", "Every flag cites source text"],
                ["💬", "Interview Qs", "Candidate-specific only"],
              ].map(([icon, title, desc]) => (
                <div key={title as string} style={{ padding: "13px 15px", background: "#0E1C2E", border: "1px solid #172840", borderRadius: 12 }}>
                  <div style={{ fontSize: 18, marginBottom: 5 }}>{icon}</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#EFF6FF", marginBottom: 2 }}>{title}</div>
                  <div style={{ fontSize: 11, color: "#64748B" }}>{desc}</div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 16, padding: "12px 16px", background: "#0E1C2E", border: "1px solid #172840", borderRadius: 12, fontSize: 12, color: "#64748B", lineHeight: 1.6 }}>
              🛡 <strong style={{ color: "#94A3B8" }}>Privacy notice:</strong> Resume text is processed securely. No data is permanently stored without your consent. HireLens assists recruiters — final hiring decisions always rest with humans.
            </div>
          </div>
        )}

        {/* ── UPLOADING ── */}
        {state.phase === "uploading" && (
          <div className="animate-fade-up" style={{ textAlign: "center", padding: "40px 0" }}>
            <div style={{ width: 56, height: 56, border: "3px solid #172840", borderTopColor: "#1D6AFF", borderRadius: "50%", margin: "0 auto 20px", animation: "spin 1s linear infinite" }} />
            <div style={{ fontSize: 16, fontWeight: 700, color: "#EFF6FF", marginBottom: 6 }}>Uploading resume…</div>
            <div style={{ fontSize: 13, color: "#64748B" }}>Sending to HireLens API</div>
          </div>
        )}

        {/* ── ANALYZING ── */}
        {state.phase === "analyzing" && (
          <div className="animate-fade-up">
            <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 20, padding: "32px 36px" }}>
              <div style={{ marginBottom: 28 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#EFF6FF", marginBottom: 4 }}>Analyzing resume</div>
                <div style={{ fontFamily: "monospace", fontSize: 11, color: "#64748B" }}>{state.job.file_name}</div>
              </div>

              {/* Live status */}
              <div style={{ padding: "12px 16px", background: "#0A1525", border: "1px solid #1E3450", borderRadius: 10, marginBottom: 24, display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ display: "flex", gap: 4 }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "#4B8DFF", animation: `pulse-dot ${1.1 + i * 0.15}s ${i * 0.15}s ease-in-out infinite` }} />
                  ))}
                </div>
                <span style={{ fontSize: 13, color: "#CBD5E1" }}>
                  {STAGES.find(s => s.key === state.job.stage)?.label || state.job.stage}
                </span>
                <span style={{ marginLeft: "auto", fontFamily: "monospace", fontSize: 12, color: "#4B8DFF" }}>{progress}%</span>
              </div>

              {/* Steps */}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {STAGES.map((s, i) => {
                  const done   = i < stageIdx;
                  const active = i === stageIdx;
                  return (
                    <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{
                        width: 24, height: 24, borderRadius: 7, flexShrink: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: done ? "rgba(5,150,105,.15)" : active ? "rgba(29,106,255,.15)" : "transparent",
                        border: `1.5px solid ${done ? "#059669" : active ? "#4B8DFF" : "#172840"}`,
                        fontSize: 11, transition: "all .3s",
                      }}>
                        {done ? <span style={{ color: "#10B981", fontWeight: 800 }}>✓</span>
                               : <span style={{ color: active ? "#4B8DFF" : "#475569" }}>{i + 1}</span>}
                      </div>
                      <span style={{ fontSize: 12, color: done ? "#10B981" : active ? "#EFF6FF" : "#475569", fontWeight: active ? 600 : 400, transition: "color .3s" }}>
                        {s.label}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Progress bar */}
              <div style={{ marginTop: 24, height: 3, background: "#172840", borderRadius: 99 }}>
                <div style={{ height: "100%", background: "linear-gradient(90deg,#1D6AFF,#22D3EE)", borderRadius: 99, width: `${Math.max(4, progress)}%`, transition: "width .6s ease" }} />
              </div>
            </div>
          </div>
        )}

        {/* ── ERROR ── */}
        {state.phase === "error" && (
          <div className="animate-fade-up" style={{ textAlign: "center" }}>
            <div style={{ background: "#0E1C2E", border: "1px solid rgba(220,38,38,.3)", borderRadius: 20, padding: "44px 32px" }}>
              <div style={{ fontSize: 40, marginBottom: 16 }}>⚠</div>
              <div style={{ fontSize: 17, fontWeight: 700, color: "#EFF6FF", marginBottom: 10 }}>Analysis Failed</div>
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
        @keyframes pulse-dot { 0%,100%{opacity:.2;transform:scale(.7)} 50%{opacity:1;transform:scale(1.1)} }
        .animate-fade-up { animation: fadeUp .3s ease forwards; }
        @keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }
      `}</style>
    </div>
  );
}
