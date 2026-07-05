"use client";
import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, APIError } from "@/lib/api";
import type { Report, Flag, Decision } from "@/types";

// ── Helpers ──────────────────────────────────────────────────────────────────
function scoreColor(n: number) {
  if (n >= 75) return "#10B981";
  if (n >= 55) return "#FBBF24";
  return "#F87171";
}

function recInfo(r: string) {
  const m: Record<string, { label: string; color: string; bg: string; border: string }> = {
    recommended:   { label: "Recommended",   color: "#10B981", bg: "rgba(5,150,105,.1)",  border: "#059669" },
    manual_review: { label: "Manual Review", color: "#FBBF24", bg: "rgba(217,119,6,.1)",  border: "#D97706" },
    high_risk:     { label: "High Risk",     color: "#F87171", bg: "rgba(220,38,38,.1)",  border: "#DC2626" },
  };
  return m[r] || m.manual_review;
}

function sevInfo(s: string) {
  const m: Record<string, { label: string; color: string; bg: string; border: string }> = {
    high:   { label: "HIGH", color: "#F87171", bg: "rgba(220,38,38,.08)",  border: "#DC2626" },
    medium: { label: "MED",  color: "#FBBF24", bg: "rgba(217,119,6,.08)",  border: "#D97706" },
    low:    { label: "LOW",  color: "#22D3EE", bg: "rgba(6,182,212,.08)",  border: "#06B6D4" },
  };
  return m[s] || m.low;
}

// ── Score Ring ────────────────────────────────────────────────────────────────
function ScoreRing({ score }: { score: number }) {
  const [w, setW] = useState(0);
  useEffect(() => { const t = setTimeout(() => setW(score), 200); return () => clearTimeout(t); }, [score]);
  const size = 110, stroke = 8;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (w / 100) * circ;
  const col = scoreColor(score);
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)", display: "block" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#172840" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={col} strokeWidth={stroke}
          strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1.4s cubic-bezier(.4,0,.2,1)", filter: `drop-shadow(0 0 8px ${col}55)` }}
        />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontFamily: "monospace", fontSize: 24, fontWeight: 800, color: col, lineHeight: 1 }}>{score}</span>
        <span style={{ fontSize: 9, color: "#64748B", letterSpacing: 2, marginTop: 3 }}>/ 100</span>
      </div>
    </div>
  );
}

// ── Score Bar ─────────────────────────────────────────────────────────────────
function ScoreBar({ label, value, rationale }: { label: string; value: number; rationale?: string }) {
  const [w, setW] = useState(0);
  const [tip, setTip] = useState(false);
  useEffect(() => { const t = setTimeout(() => setW(value), 150); return () => clearTimeout(t); }, [value]);
  const col = scoreColor(value);
  return (
    <div style={{ marginBottom: 14, position: "relative" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "#94A3B8", cursor: rationale ? "help" : "default" }}
          onMouseOver={() => rationale && setTip(true)} onMouseOut={() => setTip(false)}>
          {label}{rationale && <span style={{ color: "#475569", marginLeft: 4, fontSize: 10 }}>ⓘ</span>}
        </span>
        <span style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: col }}>{value}</span>
      </div>
      <div style={{ height: 4, background: "#172840", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${w}%`, background: `linear-gradient(90deg,${col}88,${col})`, borderRadius: 99, transition: "width 1.3s cubic-bezier(.4,0,.2,1)" }} />
      </div>
      {tip && rationale && (
        <div style={{ position: "absolute", bottom: "110%", left: 0, right: 0, background: "#0E1C2E", border: "1px solid #1E3450", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: "#CBD5E1", zIndex: 10, lineHeight: 1.5 }}>
          {rationale}
        </div>
      )}
    </div>
  );
}

// ── Flag Card ─────────────────────────────────────────────────────────────────
function FlagCard({ flag }: { flag: Flag }) {
  const [open, setOpen] = useState(false);
  const si = sevInfo(flag.severity);
  return (
    <div style={{ background: si.bg, border: `1px solid ${si.border}25`, borderLeft: `3px solid ${si.color}`, borderRadius: 10, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "13px 16px", cursor: "pointer" }} onClick={() => setOpen(o => !o)}>
        <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 10, fontWeight: 800, color: si.color, background: `${si.color}18`, letterSpacing: ".08em", flexShrink: 0, marginTop: 1 }}>{si.label}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#EFF6FF", flex: 1 }}>{flag.title}</span>
        <span style={{ color: "#64748B", fontSize: 11, flexShrink: 0 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: "#CBD5E1", lineHeight: 1.65 }}>{flag.description}</p>
          <div style={{ fontFamily: "monospace", fontSize: 11, color: "#64748B", background: "#0A1525", padding: "8px 12px", borderRadius: 6, lineHeight: 1.6 }}>
            ↳ Evidence: {flag.evidence}
          </div>
          {flag.action && <div style={{ fontSize: 12, color: "#4B8DFF" }}>✦ Action: {flag.action}</div>}
        </div>
      )}
    </div>
  );
}

// ── Main Report Page ──────────────────────────────────────────────────────────
export default function ReportPage() {
  const params  = useParams<{ id: string }>();
  const router  = useRouter();
  const { token, logout } = useAuthStore();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState<string | null>(null);
  const [tab, setTab]       = useState("overview");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) { router.replace("/login"); return; }
  }, [token, router]);

  useEffect(() => {
    if (!token || !params.id) return;
    (async () => {
      try {
        const r = await reportsAPI.get(params.id, token);
        setReport(r);
        setDecision(r.recruiter_decision);
      } catch (e) {
        if (e instanceof APIError && e.status === 401) { logout(); router.replace("/login"); }
        else setError(e instanceof APIError ? e.message : "Failed to load report.");
      } finally {
        setLoading(false);
      }
    })();
  }, [params.id, token, logout, router]);

  const submitDecision = useCallback(async (d: Decision) => {
    if (!token || !params.id) return;
    setDecision(d);
    setSaving(true);
    try { await reportsAPI.decision(params.id, d, undefined, token); }
    catch { /* silent fail — decision still shown locally */ }
    setSaving(false);
  }, [token, params.id]);

  if (loading) return (
    <div style={{ minHeight: "100vh", background: "#060F1A", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: "#64748B", fontSize: 14 }}>Loading report…</div>
    </div>
  );

  if (error || !report) return (
    <div style={{ minHeight: "100vh", background: "#060F1A", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16 }}>
      <div style={{ color: "#F87171", fontSize: 14 }}>{error || "Report not found."}</div>
      <Link href="/dashboard" style={{ color: "#4B8DFF", fontSize: 13 }}>← Back to Dashboard</Link>
    </div>
  );

  const cred     = report.credibility || {} as any;
  const scores   = cred.sub_scores || {} as any;
  const rationale = cred.score_rationale || {} as any;
  const ri       = recInfo(cred.recommendation || "manual_review");
  const flags    = report.flags || [];
  const highFlags = flags.filter(f => f.severity === "high").length;

  const TABS = [
    { id: "overview",   label: "Overview" },
    { id: "flags",      label: `Flags (${flags.length})` },
    { id: "skills",     label: "Skills" },
    { id: "timeline",   label: "Timeline" },
    { id: "questions",  label: "Interview Qs" },
    { id: "json",       label: "JSON" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#060F1A" }}>
      <style>{`@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}.fu{animation:fadeUp .3s ease}`}</style>

      {/* Navbar */}
      <nav style={{ height: 54, borderBottom: "1px solid #172840", display: "flex", alignItems: "center", paddingInline: 24, gap: 16, position: "sticky", top: 0, background: "rgba(6,15,26,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EFF6FF", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <span style={{ color: "#172840" }}>|</span>
        <span style={{ fontSize: 13, color: "#64748B" }}>Report</span>
        <div style={{ flex: 1 }} />
        <Link href="/analyze" style={{ padding: "6px 16px", borderRadius: 8, background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 600, fontSize: 12, textDecoration: "none" }}>
          + New Analysis
        </Link>
      </nav>

      <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 20px 80px" }}>
        <Link href="/dashboard" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#64748B", textDecoration: "none", marginBottom: 20 }}>
          ← Dashboard
        </Link>

        {/* Header card */}
        <div className="fu" style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 20, overflow: "hidden", marginBottom: 12 }}>

          {/* Top section */}
          <div style={{ padding: "22px 28px", borderBottom: "1px solid #172840", display: "flex", gap: 22, alignItems: "flex-start", flexWrap: "wrap" }}>
            <ScoreRing score={cred.overall || 0} />
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <h2 style={{ margin: 0, fontSize: 22, fontWeight: 900, color: "#EFF6FF", letterSpacing: -.5 }}>
                  {report.candidate?.name || "Unknown Candidate"}
                </h2>
                <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, color: ri.color, background: ri.bg, border: `1px solid ${ri.border}44` }}>
                  ● {ri.label}
                </span>
                {highFlags > 0 && (
                  <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, color: "#F87171", background: "rgba(220,38,38,.1)" }}>
                    {highFlags} high-risk flag{highFlags > 1 ? "s" : ""}
                  </span>
                )}
              </div>
              {report.candidate?.current_role && (
                <div style={{ fontSize: 13, color: "#4B8DFF", marginBottom: 6 }}>{report.candidate.current_role}</div>
              )}
              <div style={{ fontSize: 12, color: "#64748B", marginBottom: 12, lineHeight: 1.7 }}>
                {[report.candidate?.email, report.candidate?.phone, report.candidate?.location].filter(Boolean).join("  ·  ") || "Contact info not found in resume"}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {(report.skills?.all_claimed || []).slice(0, 8).map(s => {
                  const v = (report.skills?.verified_by_evidence || []).includes(s);
                  return (
                    <span key={s} style={{ padding: "4px 10px", borderRadius: 7, fontSize: 11, fontWeight: 600, color: v ? "#10B981" : "#FBBF24", background: v ? "rgba(5,150,105,.1)" : "rgba(217,119,6,.1)", border: `1px solid ${v ? "#059669" : "#D97706"}33` }}>
                      {v ? "✓" : "?"} {s}
                    </span>
                  );
                })}
                {(report.skills?.all_claimed?.length || 0) > 8 && (
                  <span style={{ fontSize: 11, color: "#64748B", alignSelf: "center" }}>
                    +{(report.skills?.all_claimed?.length || 0) - 8} more
                  </span>
                )}
              </div>
            </div>
            <div style={{ flexShrink: 0, textAlign: "right" }}>
              <div style={{ fontFamily: "monospace", fontSize: 11, color: "#475569", marginBottom: 4 }}>{report.file_name}</div>
              <div style={{ fontFamily: "monospace", fontSize: 11, color: "#475569" }}>
                {report.created_at ? new Date(report.created_at).toLocaleDateString() : "Just analyzed"}
              </div>
            </div>
          </div>

          {/* One-liner */}
          {report.one_liner && (
            <div style={{ padding: "10px 28px", background: "rgba(29,106,255,.06)", borderBottom: "1px solid #172840" }}>
              <span style={{ fontSize: 13, color: "#CBD5E1", fontStyle: "italic" }}>&ldquo;{report.one_liner}&rdquo;</span>
            </div>
          )}

          {/* Tabs */}
          <div style={{ display: "flex", borderBottom: "1px solid #172840", overflowX: "auto" }}>
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)} style={{ padding: "12px 16px", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit", color: tab === t.id ? "#4B8DFF" : "#64748B", borderBottom: `2px solid ${tab === t.id ? "#1D6AFF" : "transparent"}`, fontWeight: tab === t.id ? 700 : 400, fontSize: 12, whiteSpace: "nowrap", transition: "color .15s" }}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div style={{ padding: "24px 28px" }}>

            {/* OVERVIEW */}
            {tab === "overview" && (
              <div className="fu">
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 48px", marginBottom: 24 }}>
                  <div>
                    <ScoreBar label="Employment Timeline"  value={scores.timeline || 0}          rationale={rationale.timeline} />
                    <ScoreBar label="Skills Consistency"  value={scores.skills_consistency || 0} rationale={rationale.skills_consistency} />
                    <ScoreBar label="Education"            value={scores.education || 0}          rationale={rationale.education} />
                  </div>
                  <div>
                    <ScoreBar label="Project Authenticity" value={scores.project_authenticity || 0} rationale={rationale.project_authenticity} />
                    <ScoreBar label="Resume Quality"       value={scores.resume_quality || 0}       rationale={rationale.resume_quality} />
                    <div style={{ fontSize: 11, color: "#475569", marginTop: 8 }}>ⓘ Hover labels to see AI rationale</div>
                  </div>
                </div>

                {/* Summary */}
                <div style={{ background: "#0A1525", border: "1px solid #172840", borderRadius: 12, padding: "18px 20px", marginBottom: 14 }}>
                  <div style={{ fontSize: 10, color: "#475569", letterSpacing: 2.5, textTransform: "uppercase", marginBottom: 10 }}>AI Recruiter Summary</div>
                  <p style={{ fontSize: 13, color: "#CBD5E1", lineHeight: 1.75, margin: 0 }}>{report.summary}</p>
                </div>

                {/* Positives */}
                {(report.positive_signals || []).length > 0 && (
                  <div style={{ background: "rgba(5,150,105,.06)", border: "1px solid rgba(5,150,105,.2)", borderRadius: 12, padding: "16px 20px" }}>
                    <div style={{ fontSize: 10, color: "#10B981", letterSpacing: 2.5, textTransform: "uppercase", marginBottom: 12 }}>Positive Signals</div>
                    {report.positive_signals!.map((p, i) => (
                      <div key={i} style={{ display: "flex", gap: 10, marginBottom: 8 }}>
                        <span style={{ color: "#10B981", flexShrink: 0 }}>✓</span>
                        <div style={{ fontSize: 13, color: "#CBD5E1" }}><strong style={{ color: "#EFF6FF" }}>{p.title}:</strong> {p.description}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* FLAGS */}
            {tab === "flags" && (
              <div className="fu">
                {flags.length === 0 ? (
                  <div style={{ textAlign: "center", padding: 40 }}>
                    <div style={{ fontSize: 36, marginBottom: 12 }}>✅</div>
                    <div style={{ fontSize: 14, color: "#10B981" }}>No significant risk flags detected</div>
                    <div style={{ fontSize: 12, color: "#64748B", marginTop: 6 }}>Resume appears consistent and well-evidenced.</div>
                  </div>
                ) : (
                  <>
                    <div style={{ fontSize: 12, color: "#64748B", marginBottom: 14 }}>
                      {flags.filter(f => f.severity === "high").length} high · {flags.filter(f => f.severity === "medium").length} medium · {flags.filter(f => f.severity === "low").length} low · Click any flag to expand
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {flags.map((f, i) => <FlagCard key={i} flag={f} />)}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* SKILLS */}
            {tab === "skills" && (
              <div className="fu">
                {report.skills?.primary_domain && (
                  <div style={{ marginBottom: 16, padding: "12px 16px", background: "rgba(29,106,255,.1)", border: "1px solid rgba(29,106,255,.25)", borderRadius: 10 }}>
                    <span style={{ fontSize: 12, color: "#4B8DFF" }}>Primary domain: </span>
                    <strong style={{ fontSize: 12, color: "#EFF6FF" }}>{report.skills.primary_domain}</strong>
                    {report.skills.keyword_stuffing_risk && report.skills.keyword_stuffing_risk !== "none" && (
                      <span style={{ marginLeft: 14, fontSize: 11, color: "#FBBF24" }}>⚠ Keyword stuffing risk: {report.skills.keyword_stuffing_risk}</span>
                    )}
                  </div>
                )}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 10, color: "#475569", letterSpacing: 2.5, textTransform: "uppercase", marginBottom: 12 }}>All Skills — Verification Status</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {(report.skills?.all_claimed || []).map(s => {
                      const v = (report.skills?.verified_by_evidence || []).includes(s);
                      return (
                        <span key={s} style={{ padding: "6px 13px", borderRadius: 9, fontSize: 12, fontWeight: 600, color: v ? "#10B981" : "#FBBF24", background: v ? "rgba(5,150,105,.1)" : "rgba(217,119,6,.1)", border: `1px solid ${v ? "#059669" : "#D97706"}33` }}>
                          {v ? "✓" : "?"} {s}
                        </span>
                      );
                    })}
                  </div>
                  <div style={{ fontSize: 11, color: "#475569", marginTop: 10 }}>✓ = found in job descriptions or projects · ? = listed only, not evidenced in work history</div>
                </div>
                {(report.skills?.domain_spread_concern) && (
                  <div style={{ padding: "14px 16px", background: "rgba(217,119,6,.08)", border: "1px solid rgba(217,119,6,.2)", borderRadius: 10 }}>
                    <div style={{ fontSize: 11, color: "#FBBF24", fontWeight: 700, marginBottom: 6 }}>DOMAIN SPREAD CONCERN</div>
                    <div style={{ fontSize: 12, color: "#CBD5E1" }}>{report.skills.domain_spread_note}</div>
                  </div>
                )}
              </div>
            )}

            {/* TIMELINE */}
            {tab === "timeline" && (
              <div className="fu">
                {(report.timeline_gaps || []).length > 0 && (
                  <div style={{ marginBottom: 20, padding: "14px 16px", background: "rgba(217,119,6,.08)", border: "1px solid rgba(217,119,6,.2)", borderRadius: 10 }}>
                    <div style={{ fontSize: 11, color: "#FBBF24", fontWeight: 700, marginBottom: 8 }}>GAPS DETECTED</div>
                    {report.timeline_gaps!.map((g, i) => (
                      <div key={i} style={{ fontSize: 12, color: "#CBD5E1", marginBottom: 5 }}>
                        {g.from} → {g.to}: <strong>{g.duration}</strong> ·{" "}
                        <span style={{ color: g.severity === "high" ? "#F87171" : g.severity === "medium" ? "#FBBF24" : "#22D3EE" }}>{g.severity} severity</span>
                        {g.note && <span style={{ color: "#64748B" }}> — {g.note}</span>}
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {(report.experience || []).map((exp, i) => (
                    <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                        <div style={{ width: 10, height: 10, borderRadius: "50%", marginTop: 4, background: exp.is_verifiable !== false ? "#4B8DFF" : "#FBBF24", boxShadow: `0 0 0 3px ${exp.is_verifiable !== false ? "#1D6AFF" : "#D97706"}33` }} />
                        {i < (report.experience || []).length - 1 && <div style={{ width: 2, flex: 1, background: "#172840", minHeight: 32, marginTop: 4 }} />}
                      </div>
                      <div style={{ paddingBottom: i < (report.experience || []).length - 1 ? 20 : 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "#EFF6FF" }}>{exp.role}</div>
                        <div style={{ fontSize: 12, color: exp.is_verifiable !== false ? "#4B8DFF" : "#FBBF24" }}>{exp.company}</div>
                        <div style={{ fontSize: 11, color: "#64748B", marginTop: 2 }}>{exp.period}</div>
                        {exp.is_verifiable === false && <div style={{ fontSize: 11, color: "#FBBF24", marginTop: 2 }}>⚠ Company not easily verifiable</div>}
                      </div>
                    </div>
                  ))}
                </div>
                {(report.education || []).length > 0 && (
                  <div style={{ marginTop: 24 }}>
                    <div style={{ fontSize: 10, color: "#475569", letterSpacing: 2.5, textTransform: "uppercase", marginBottom: 14 }}>Education</div>
                    {report.education!.map((e, i) => (
                      <div key={i} style={{ padding: "12px 16px", background: "#0A1525", border: "1px solid #172840", borderRadius: 10, marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "#EFF6FF" }}>{e.degree}</div>
                        <div style={{ fontSize: 12, color: e.is_recognized_institution !== false ? "#4B8DFF" : "#FBBF24" }}>{e.institution}</div>
                        <div style={{ fontSize: 11, color: "#64748B" }}>{e.period}</div>
                        {e.concern && <div style={{ fontSize: 11, color: "#FBBF24", marginTop: 4 }}>⚠ {e.concern}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* INTERVIEW QUESTIONS */}
            {tab === "questions" && (
              <div className="fu">
                <div style={{ fontSize: 12, color: "#64748B", marginBottom: 16 }}>Generated from this candidate&apos;s specific signals — not generic templates</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {(report.interview_questions || []).map((q, i) => (
                    <div key={i} style={{ display: "flex", gap: 14, padding: "15px 18px", background: "#0A1525", border: "1px solid #172840", borderRadius: 12 }}>
                      <span style={{ fontFamily: "monospace", fontSize: 11, color: "#4B8DFF", flexShrink: 0, paddingTop: 2, minWidth: 28, fontWeight: 800 }}>Q{i + 1}</span>
                      <div>
                        <div style={{ fontSize: 13, color: "#EFF6FF", lineHeight: 1.65, fontWeight: 500, marginBottom: q.rationale ? 6 : 0 }}>{q.question}</div>
                        {q.rationale && <div style={{ fontSize: 11, color: "#64748B", lineHeight: 1.5 }}>↳ {q.rationale}</div>}
                        {q.targets_flag && <div style={{ fontSize: 11, color: "#FBBF24", marginTop: 3 }}>⚑ Targets: {q.targets_flag}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* RAW JSON */}
            {tab === "json" && (
              <div className="fu">
                <div style={{ fontSize: 12, color: "#64748B", marginBottom: 12 }}>Full structured output — use via API for ATS/HRIS integration</div>
                <pre style={{ background: "#0A1525", border: "1px solid #172840", borderRadius: 12, padding: 18, fontSize: 10.5, color: "#94A3B8", overflow: "auto", fontFamily: "monospace", lineHeight: 1.75, margin: 0, maxHeight: 500 }}>
                  {JSON.stringify(report, null, 2)}
                </pre>
              </div>
            )}

          </div>
        </div>

        {/* Decision panel */}
        <div className="fu" style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, padding: "18px 24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontSize: 10, color: "#475569", letterSpacing: 2.5, textTransform: "uppercase" }}>Recruiter Decision</div>
            <div style={{ fontSize: 11, color: "#475569", fontStyle: "italic" }}>
              {saving ? "Saving…" : "Your decision trains the AI model"}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {([
              { val: "advance",           label: "Advance to Interview", color: "#10B981", bg: "rgba(5,150,105,.1)",  border: "#059669" },
              { val: "schedule_followup", label: "Request More Info",    color: "#FBBF24", bg: "rgba(217,119,6,.1)", border: "#D97706" },
              { val: "reject",            label: "Not a Match",          color: "#F87171", bg: "rgba(220,38,38,.1)", border: "#DC2626" },
            ] as const).map(d => (
              <button key={d.val} onClick={() => submitDecision(d.val)}
                style={{ padding: "10px 18px", borderRadius: 10, cursor: "pointer", fontFamily: "inherit", fontSize: 12, fontWeight: 600, color: d.color, background: decision === d.val ? d.bg : "transparent", border: `1.5px solid ${decision === d.val ? d.border : "#172840"}`, transition: "all .15s" }}>
                {d.label}
              </button>
            ))}
            {decision && <div style={{ marginLeft: "auto", alignSelf: "center", fontSize: 12, color: "#10B981" }}>✓ Recorded</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
