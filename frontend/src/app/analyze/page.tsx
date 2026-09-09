"use client";
import { useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import {
  Zap,
  FileText,
  BarChart3,
  AlertTriangle,
  MessageSquare,
  ShieldCheck,
  Check,
  AlertCircle,
} from "lucide-react";
import { useAnalysis } from "@/hooks/useAnalysis";
import { color, gradient, radius } from "@/lib/design-tokens";
import { Card, Button, PageShell } from "@/components/ui/primitives";
import { AppNavbar } from "@/components/ui/AppNavbar";

const STAGES = [
  { key: "queued",     label: "Preparing document upload" },
  { key: "parsing",   label: "Extracting raw document text & structure" },
  { key: "extracting", label: "Parsing work history, skills & timeline" },
  { key: "analyzing", label: "Running Deep Decision Intelligence Analysis" },
  { key: "complete",  label: "Building report" },
];

export default function AnalyzePage() {
  const router   = useRouter();
  const { token, sessionChecked } = useAuthStore();
  const { state, analyze, reset } = useAnalysis();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (sessionChecked && !token) router.replace("/login");
  }, [sessionChecked, token, router]);

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
    <PageShell>
      <AppNavbar />

      {/* Main Container */}
      <div style={{ maxWidth: 680, margin: "0 auto", padding: "48px 24px" }}>

        {/* ── IDLE: Upload form ── */}
        {state.phase === "idle" && (
          <div className="animate-fade-up">
            <div style={{ marginBottom: 32, textAlign: "center" }}>
              <h1 className="font-display" style={{ fontSize: 30, fontWeight: 600, color: color.textPrimary, margin: "0 0 12px" }}>
                Analyze a resume
              </h1>
              <p style={{ fontSize: 15, color: color.textMuted, margin: 0, lineHeight: 1.6 }}>
                Upload a real PDF or DOCX file. HireLens parses the actual content<br />
                and returns a deep credibility assessment in under 30 seconds.
              </p>
            </div>

            {/* Drop zone — flat surface, hairline border, no blur/glow */}
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              style={{
                border: `1.5px dashed ${color.border}`,
                borderRadius: radius.lg, padding: "48px 32px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 18,
                cursor: "pointer", background: color.surface,
                transition: "border-color 0.15s ease, background-color 0.15s ease", textAlign: "center",
              }}
              onMouseOver={e => {
                (e.currentTarget as HTMLElement).style.borderColor = color.brand;
                (e.currentTarget as HTMLElement).style.background = color.surfaceRaised;
              }}
              onMouseOut={e => {
                (e.currentTarget as HTMLElement).style.borderColor = color.border;
                (e.currentTarget as HTMLElement).style.background = color.surface;
              }}
            >
              <input ref={inputRef} type="file" accept=".pdf,.docx" style={{ display: "none" }} onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />

              <div style={{
                width: 64, height: 64, borderRadius: radius.lg,
                background: color.surfaceRaised,
                border: `1px solid ${color.border}`,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}><FileText size={28} color={color.brandLight} /></div>

              <div>
                <div style={{ fontSize: 16, fontWeight: 600, color: color.textPrimary, marginBottom: 6 }}>Drop a resume here</div>
                <div style={{ fontSize: 13, color: color.textMuted }}>PDF or DOCX, up to 10MB</div>
              </div>

              <div style={{
                padding: "10px 24px", borderRadius: radius.md,
                background: color.brand,
                color: "#F5F5F2", fontWeight: 600, fontSize: 13.5,
              }}>
                Choose file
              </div>
            </div>

            {/* Feature Cards Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 24 }}>
              {[
                { icon: <Zap size={18} color={color.brandLight} />, title: "Deep Decision Engine", desc: "Frontier-class semantic intelligence" },
                { icon: <BarChart3 size={18} color={color.info} />, title: "Credibility Score", desc: "Evidence-linked 0–100 rating" },
                { icon: <AlertTriangle size={18} color={color.danger} />, title: "Risk Flags", desc: "Cites exact candidate text" },
                { icon: <MessageSquare size={18} color={color.success} />, title: "Custom Interview Qs", desc: "Targeted probe questions" },
              ].map(({ icon, title, desc }) => (
                <Card key={title} style={{ padding: "16px 18px" }}>
                  <div style={{ marginBottom: 8 }}>{icon}</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary, marginBottom: 2 }}>{title}</div>
                  <div style={{ fontSize: 12, color: color.textMuted }}>{desc}</div>
                </Card>
              ))}
            </div>

            <div style={{ marginTop: 20, padding: "13px 16px", background: color.surface, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md, fontSize: 12, color: color.textMuted, lineHeight: 1.6, display: "flex", alignItems: "center", gap: 10 }}>
              <ShieldCheck size={16} color={color.success} style={{ flexShrink: 0 }} />
              <span><strong style={{ color: color.textSecondary }}>Privacy:</strong> resume data is processed securely and never shared outside your workspace.</span>
            </div>
          </div>
        )}

        {/* ── UPLOADING ── */}
        {state.phase === "uploading" && (
          <div className="animate-fade-up" style={{ textAlign: "center", padding: "48px 0" }}>
            <div style={{ width: 48, height: 48, border: `3px solid ${color.border}`, borderTopColor: color.brand, borderRadius: "50%", margin: "0 auto 24px" }} className="animate-spin" />
            <div style={{ fontSize: 16, fontWeight: 600, color: color.textPrimary, marginBottom: 6 }}>Uploading resume…</div>
            <div style={{ fontSize: 14, color: color.textMuted }}>Sending to HireLens API</div>
          </div>
        )}

        {/* ── ANALYZING ── */}
        {state.phase === "analyzing" && (
          <div className="animate-fade-up">
            <Card style={{ padding: "32px 36px" }}>
              <div style={{ marginBottom: 28 }}>
                <div className="font-display" style={{ fontSize: 19, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>Analyzing resume</div>
                <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 12, color: color.brandLight }}>{state.job.file_name}</div>
              </div>

              {/* Live status bar */}
              <div style={{ padding: "13px 16px", background: color.bgAlt, border: `1px solid ${color.border}`, borderRadius: radius.md, marginBottom: 28, display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ display: "flex", gap: 4 }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{ width: 7, height: 7, borderRadius: "50%", background: color.brand, animation: `pulse-dot ${1.1 + i * 0.15}s ${i * 0.15}s ease-in-out infinite` }} />
                  ))}
                </div>
                <span style={{ fontSize: 14, color: color.textPrimary, fontWeight: 600 }}>
                  {STAGES.find(s => s.key === state.job.stage)?.label || state.job.stage}
                </span>
                <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono), monospace", fontSize: 13, color: color.brandLight, fontWeight: 600 }}>{progress}%</span>
              </div>

              {/* Stage Steps */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {STAGES.map((s, i) => {
                  const done   = i < stageIdx;
                  const active = i === stageIdx;
                  return (
                    <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{
                        width: 26, height: 26, borderRadius: radius.sm, flexShrink: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: done ? color.successBg : active ? color.surfaceRaised : "transparent",
                        border: `1.5px solid ${done ? color.success : active ? color.brand : color.border}`,
                        fontSize: 12, transition: "all 0.3s",
                      }}>
                        {done ? <Check size={14} color={color.success} strokeWidth={3} />
                               : <span style={{ color: active ? color.brandLight : color.textFaint }}>{i + 1}</span>}
                      </div>
                      <span style={{ fontSize: 13, color: done ? color.success : active ? color.textPrimary : color.textFaint, fontWeight: active ? 600 : 400 }}>
                        {s.label}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Progress bar */}
              <div style={{ marginTop: 28, height: 4, background: color.border, borderRadius: radius.pill }}>
                <div style={{ height: "100%", background: color.brand, borderRadius: radius.pill, width: `${Math.max(5, progress)}%`, transition: "width 0.6s ease" }} />
              </div>
            </Card>
          </div>
        )}

        {/* ── ERROR ── */}
        {state.phase === "error" && (
          <div className="animate-fade-up" style={{ textAlign: "center" }}>
            <Card style={{ border: `1px solid ${color.dangerBorder}`, padding: "40px 32px" }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}>
                <AlertCircle size={44} color={color.danger} />
              </div>
              <div className="font-display" style={{ fontSize: 19, fontWeight: 600, color: color.textPrimary, marginBottom: 10 }}>Analysis failed</div>
              <div style={{ fontSize: 14, color: color.textMuted, lineHeight: 1.6, marginBottom: 28 }}>{state.message}</div>
              <Button onClick={reset} style={{ padding: "12px 32px" }}>
                Try Again
              </Button>
            </Card>
          </div>
        )}


      </div>
    </PageShell>
  );
}
