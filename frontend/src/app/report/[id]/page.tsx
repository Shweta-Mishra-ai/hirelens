"use client";
import { useEffect, useState, useCallback, type ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, verifyAPI, teamsAPI, collaborationAPI, copilotAPI, APIError } from "@/lib/api";
import type { Report, Flag, Decision, VerificationResult, Team, ReportComment, VotesResult } from "@/types";
import { VerdictStamp, verdictFromRecommendation, type VerdictKind } from "@/components/VerdictStamp";
import {
  Search,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Cpu,
  UserCheck,
  Star,
  Check,
  Mail,
  Edit2,
  FileText,
  Shield,
  Send,
  Clock,
  Minus,
  X as XIcon,
} from "lucide-react";

// ── Helpers ──────────────────────────────────────────────────────────────────
function scoreColor(n: number) {
  if (n >= 75) return "#5C9A6C";
  if (n >= 55) return "#B98A3E";
  return "#B3543A";
}


function sevInfo(s: string) {
  const m: Record<string, { label: string; color: string; bg: string; border: string }> = {
    high:   { label: "High", color: "#B3543A", bg: "rgba(179,84,58,.08)",  border: "#B3543A" },
    medium: { label: "Med",  color: "#B98A3E", bg: "rgba(185,138,62,.08)",  border: "#B98A3E" },
    low:    { label: "Low",  color: "#5B84A6", bg: "rgba(91,132,166,.08)",  border: "#5B84A6" },
  };
  return m[s] || m.low;
}

// ── Verify Tab: status → badge maps ─────────────────────────────────────────
type StatusBadge = { icon: ReactNode; label: string; color: string };

const GITHUB_STATUS_MAP: Record<string, StatusBadge> = {
  verified:            { icon: <Check size={13} strokeWidth={3} />, label: "Verified",         color: "#5C9A6C" },
  partial:             { icon: <Clock size={13} />,                 label: "Partial Match",    color: "#B98A3E" },
  no_public_activity:  { icon: <Minus size={13} />,                 label: "No Public Repos",  color: "#B4B4AC" },
  not_found:           { icon: <XIcon size={13} strokeWidth={3} />, label: "Account Not Found", color: "#B3543A" },
  no_username:         { icon: <Minus size={13} />,                 label: "No Username",      color: "#B4B4AC" },
  rate_limited:        { icon: <AlertTriangle size={13} />,         label: "Rate Limited",     color: "#B98A3E" },
  error:               { icon: <AlertTriangle size={13} />,         label: "Check Failed",     color: "#B98A3E" },
};

const EDU_STATUS_MAP: Record<string, StatusBadge> = {
  verified:  { icon: <Check size={13} strokeWidth={3} />, label: "Verified",        color: "#5C9A6C" },
  not_found: { icon: <HelpCircle size={13} />,            label: "Not in Registry", color: "#B98A3E" },
  skipped:   { icon: <Minus size={13} />,                 label: "Skipped",         color: "#B4B4AC" },
  error:     { icon: <AlertTriangle size={13} />,         label: "Check Failed",    color: "#B98A3E" },
};

const CERT_STATUS_MAP: Record<string, StatusBadge> = {
  verified_via_link:                 { icon: <Check size={13} strokeWidth={3} />, label: "Verified",                  color: "#5C9A6C" },
  link_reachable_name_not_confirmed: { icon: <Clock size={13} />,                 label: "Link Works, Name Unconfirmed", color: "#B98A3E" },
  link_unreachable:                  { icon: <XIcon size={13} strokeWidth={3} />, label: "Link Unreachable",          color: "#B3543A" },
  no_link_provided:                  { icon: <Minus size={13} />,                 label: "No Link on Resume",         color: "#B4B4AC" },
  error:                             { icon: <AlertTriangle size={13} />,         label: "Check Failed",              color: "#B98A3E" },
};

const EXP_STATUS_MAP: Record<string, StatusBadge> = {
  domain_found:     { icon: <Check size={13} strokeWidth={3} />, label: "Website Found",     color: "#5C9A6C" },
  domain_not_found: { icon: <HelpCircle size={13} />,            label: "Website Not Found", color: "#B98A3E" },
  skipped:          { icon: <Minus size={13} />,                 label: "Skipped",           color: "#B4B4AC" },
};

function TrustAssessmentCard({ trust }: { trust: { verdict: string; score: number; reasoning: string[]; evidence_available: boolean } }) {
  const m: Record<string, { label: string; color: string; bg: string; border: string; icon: ReactNode }> = {
    high_confidence:      { label: "High Confidence — Evidence Supports This Resume", color: "#5C9A6C", bg: "rgba(92,154,108,0.08)",  border: "rgba(92,154,108,0.3)",  icon: <CheckCircle2 size={20} color="#5C9A6C" /> },
    moderate_confidence:  { label: "Moderate Confidence",                             color: "#B98A3E", bg: "rgba(185,138,62,0.08)", border: "rgba(185,138,62,0.3)", icon: <Clock size={20} color="#B98A3E" /> },
    low_confidence:       { label: "Low Confidence — Recommend Closer Review",        color: "#B3543A", bg: "rgba(179,84,58,0.08)",  border: "rgba(179,84,58,0.3)",  icon: <AlertTriangle size={20} color="#B3543A" /> },
    insufficient_evidence:{ label: "Insufficient Evidence to Assess",                 color: "#B4B4AC", bg: "rgba(148,163,184,0.08)",border: "rgba(148,163,184,0.3)",icon: <HelpCircle size={20} color="#B4B4AC" /> },
  };
  const style = m[trust.verdict] || m.insufficient_evidence;

  return (
    <div style={{ background: style.bg, border: `1.5px solid ${style.border}`, borderRadius: 6, padding: "18px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ display: "inline-flex", alignItems: "center" }}>{style.icon}</span>
        <div>
          <div className="font-display" style={{ fontSize: 16, fontWeight: 600, color: style.color }}>{style.label}</div>
          <div style={{ fontSize: 10, color: "#8A8B82", letterSpacing: 0.2, marginTop: 2 }}>
            Combined Trust Assessment — deterministic, not another AI guess
          </div>
        </div>
      </div>

      {!trust.evidence_available && (
        <p style={{ fontSize: 12, color: "#B4B4AC", lineHeight: 1.6, margin: "0 0 10px" }}>
          No independently-verifiable evidence (GitHub, education registry) was found either way.
          This is not a red flag — it means public data alone can&apos;t confirm or dispute this
          candidate. Consider it in context with the interview.
        </p>
      )}

      <details>
        <summary style={{ fontSize: 11, color: style.color, cursor: "pointer", fontWeight: 600, letterSpacing: 0.3 }}>
          Show reasoning ({trust.reasoning.length} signal{trust.reasoning.length !== 1 ? "s" : ""} considered)
        </summary>
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
          {trust.reasoning.map((r, i) => (
            <li key={i} style={{ fontSize: 12, color: "#B4B4AC", lineHeight: 1.6 }}>{r}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function AIContentCard({ analysis }: { analysis: { likelihood: string; indicators: string[]; human_indicators: string[]; note: string } }) {
  const m: Record<string, { label: string; color: string; bg: string; border: string; icon: ReactNode }> = {
    low:    { label: "Low AI-Generation Likelihood",    color: "#5C9A6C", bg: "rgba(92,154,108,0.06)",  border: "rgba(92,154,108,0.25)",  icon: <UserCheck size={16} color="#5C9A6C" /> },
    medium: { label: "Some AI-Writing Patterns Found",  color: "#B98A3E", bg: "rgba(185,138,62,0.06)",  border: "rgba(185,138,62,0.25)",  icon: <HelpCircle size={16} color="#B98A3E" /> },
    high:   { label: "High AI-Generation Likelihood",   color: "#B3543A", bg: "rgba(179,84,58,0.06)",  border: "rgba(179,84,58,0.25)",  icon: <Cpu size={16} color="#B3543A" /> },
  };
  const style = m[analysis.likelihood] || m.low;

  return (
    <div style={{ background: style.bg, border: `1px solid ${style.border}`, borderRadius: 8, padding: "16px 20px", marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span style={{ display: "inline-flex", alignItems: "center" }}>{style.icon}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: style.color, letterSpacing: 0.2 }}>{style.label}</span>
      </div>

      {analysis.note && <p style={{ fontSize: 13, color: "#CBD5E1", lineHeight: 1.65, margin: "0 0 12px" }}>{analysis.note}</p>}

      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
        {analysis.indicators.length > 0 && (
          <div style={{ flex: "1 1 240px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#B3543A", marginBottom: 6, letterSpacing: 0.5 }}>AI-PATTERN INDICATORS</div>
            {analysis.indicators.map((s, i) => (
              <div key={i} style={{ fontSize: 12, color: "#B4B4AC", marginBottom: 5, paddingLeft: 14, position: "relative" }}>
                <span style={{ position: "absolute", left: 0 }}>•</span>{s}
              </div>
            ))}
          </div>
        )}
        {analysis.human_indicators.length > 0 && (
          <div style={{ flex: "1 1 240px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#5C9A6C", marginBottom: 6, letterSpacing: 0.5 }}>AUTHENTIC-WRITING SIGNS</div>
            {analysis.human_indicators.map((s, i) => (
              <div key={i} style={{ fontSize: 12, color: "#B4B4AC", marginBottom: 5, paddingLeft: 14, position: "relative" }}>
                <span style={{ position: "absolute", left: 0 }}>•</span>{s}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function VerifyCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "12px 18px", borderBottom: "1px solid rgba(237, 237, 234, 0.08)", fontSize: 13, fontWeight: 600, color: "#EDEDEA" }}>
        {title}
      </div>
      <div style={{ padding: "6px 18px 12px" }}>{children}</div>
    </div>
  );
}

function EmptyNote({ text }: { text: string }) {
  return <div style={{ fontSize: 12, color: "#B4B4AC", padding: "10px 0" }}>{text}</div>;
}

/**
 * Only ever put an http(s) URL in an href.
 *
 * The one dynamic href on this page is a certification link, and that value
 * originates in the CANDIDATE'S RESUME — the least trustworthy input in the
 * whole product. An `href` accepts `javascript:` and `data:` URLs, and React
 * does not block them (it warns and renders), so a link scheme is a script
 * execution primitive one click away from the recruiter's session.
 *
 * That is not currently reachable: the backend extracts these links with a
 * regex anchored to `https?://` (URL_RE in certification_verify.py), so no
 * other scheme can survive into the stored report. This check exists anyway,
 * because a page rendering attacker-authored data should not be one regex
 * edit three services away from being an XSS sink — and nothing in this file
 * would tell you that regex was load-bearing.
 */
function httpUrlOrNull(raw: string | undefined): string | null {
  if (!raw) return null;
  try {
    const parsed = new URL(raw, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function VerifyRow({
  label, status, statusMap, detail, link,
}: {
  label: string;
  status: string;
  statusMap: Record<string, StatusBadge>;
  detail?: string;
  link?: string;
}) {
  const b = statusMap[status] || { icon: <HelpCircle size={13} />, label: status, color: "#B4B4AC" };
  const safeLink = httpUrlOrNull(link);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 0", borderTop: "1px solid rgba(237, 237, 234, 0.08)" }}>
      <span style={{ color: b.color, minWidth: 16, display: "inline-flex", alignItems: "center", marginTop: 2 }}>{b.icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "#EDEDEA", fontWeight: 600 }}>{label}</div>
        {detail && <div style={{ fontSize: 11, color: "#B4B4AC", marginTop: 2, lineHeight: 1.5 }}>{detail}</div>}
        {safeLink && (
          <a href={safeLink} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: "#5B84A6", textDecoration: "none" }}>
            View link ↗
          </a>
        )}
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, color: b.color, whiteSpace: "nowrap" }}>{b.label}</span>
    </div>
  );
}

function GithubVerifyBlock({ g }: { g: VerificationResult["github"] }) {
  if (!g) return null;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 0 6px" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#EDEDEA" }}>
          {g.username ? `@${g.username}` : "No username detected"}
        </span>
        <span style={{ fontSize: 11, fontWeight: 600, color: GITHUB_STATUS_MAP[g.status]?.color || "#B4B4AC" }}>
          {GITHUB_STATUS_MAP[g.status]?.label || g.status}
        </span>
      </div>

      {typeof g.public_repos === "number" && (
        <div style={{ fontSize: 11, color: "#B4B4AC", marginBottom: 8 }}>{g.public_repos} public repositories</div>
      )}

      {!!g.top_languages?.length && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {g.top_languages.map((l) => (
            <span key={l} style={{ fontSize: 10, color: "#B4B4AC", background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", padding: "2px 8px", borderRadius: 999 }}>{l}</span>
          ))}
        </div>
      )}

      {(!!g.verified_skills?.length || !!g.unverified_skills?.length) && (
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 8 }}>
          {!!g.verified_skills?.length && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#5C9A6C", marginBottom: 4, display: "flex", alignItems: "center", gap: 4 }}>
                <Check size={11} strokeWidth={3} />
                <span>VERIFIED</span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {g.verified_skills.map((s) => <span key={s} style={{ fontSize: 10, color: "#A7F3D0", background: "rgba(92,154,108,0.12)", padding: "2px 8px", borderRadius: 999 }}>{s}</span>)}
              </div>
            </div>
          )}
          {!!g.unverified_skills?.length && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#B4B4AC", marginBottom: 4 }}>NOT FOUND IN REPOS</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {g.unverified_skills.map((s) => <span key={s} style={{ fontSize: 10, color: "#B4B4AC", background: "#191B22", padding: "2px 8px", borderRadius: 999 }}>{s}</span>)}
              </div>
            </div>
          )}
        </div>
      )}

      {g.note && <div style={{ fontSize: 11, color: "#B4B4AC", marginTop: 8, lineHeight: 1.5 }}>{g.note}</div>}
    </div>
  );
}

// ── Score Docket ──────────────────────────────────────────────────────────────
// Deliberately NOT a circular progress ring — every resume tool uses one.
// This reads like a docket number stamped on a case file: a large serif
// figure, a thin rule, and the verdict stamp riding beside it.
function ScoreDocket({ score, verdict }: { score: number; verdict: VerdictKind }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setShown(score), 150);
    return () => clearTimeout(t);
  }, [score]);
  const col = scoreColor(score);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20, flexShrink: 0 }}>
      <div style={{ textAlign: "center" }}>
        <div
          className="font-display"
          style={{
            fontSize: 56, fontWeight: 600, lineHeight: 1, color: col,
            fontVariantNumeric: "tabular-nums", transition: "color .4s",
          }}
        >
          {shown}
        </div>
        <div style={{ fontSize: 10, color: "#8A8B82", letterSpacing: 0.3, marginTop: 6 }}>
          Credibility / 100
        </div>
      </div>
      <div style={{ width: 1, height: 56, background: "rgba(237, 237, 234, 0.08)" }} />
      <VerdictStamp verdict={verdict} size="lg" />
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
    <div style={{ marginBottom: 16, position: "relative" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 13, color: "#CBD5E1", fontWeight: 500, cursor: rationale ? "help" : "default" }}
          onMouseOver={() => rationale && setTip(true)} onMouseOut={() => setTip(false)}>
          {label}{rationale && <span style={{ color: "#B4B4AC", marginLeft: 6, fontSize: 11 }}>ⓘ</span>}
        </span>
        <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: 13, fontWeight: 600, color: col }}>{value}</span>
      </div>
      <div style={{ height: 6, background: "rgba(237, 237, 234, 0.08)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${w}%`, background: `linear-gradient(90deg, ${col}88, ${col})`, borderRadius: 99, transition: "width 1.3s cubic-bezier(.4,0,.2,1)" }} />
      </div>
      {tip && rationale && (
        <div style={{ position: "absolute", bottom: "110%", left: 0, right: 0, background: "#191B22", border: "1px solid rgba(59, 125, 120, 0.4)", borderRadius: 10, padding: "10px 14px", fontSize: 12, color: "#EDEDEA", zIndex: 10, lineHeight: 1.5, boxShadow: "0 8px 24px rgba(0,0,0,0.5)" }}>
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
        <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 10, fontWeight: 600, color: si.color, background: `${si.color}18`, letterSpacing: ".08em", flexShrink: 0, marginTop: 1 }}>{si.label}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#EDEDEA", flex: 1 }}>{flag.title}</span>
        <span style={{ color: "#B4B4AC", fontSize: 11, flexShrink: 0 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 13, color: "#CBD5E1", lineHeight: 1.65 }}>{flag.description}</p>
          {flag.evidence && (
            <div style={{ fontSize: 10, color: "#8A8B82", letterSpacing: 0.2 }}>
              Evidence from resume<br />
              <span className="evidence-quote" style={{ fontSize: 13, display: "inline-block", marginTop: 4, lineHeight: 1.6 }}>
                &ldquo;{flag.evidence}&rdquo;
              </span>
            </div>
          )}
          {flag.action && <div style={{ fontSize: 12, color: "#5B84A6", fontWeight: 600 }}>Action: {flag.action}</div>}
        </div>
      )}
    </div>
  );
}

// ── Main Report Page ──────────────────────────────────────────────────────────
export default function ReportPage() {
  const params  = useParams<{ id: string }>();
  const router  = useRouter();
  const { token, logout, sessionChecked } = useAuthStore();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState<string | null>(null);
  const [tab, setTab]       = useState("overview");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [saving, setSaving] = useState(false);
  const [notifyState, setNotifyState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [notifyMessage, setNotifyMessage] = useState<string | null>(null);
  const [notifyEditorOpen, setNotifyEditorOpen] = useState(false);
  const [notifyDraft, setNotifyDraft] = useState<{ subject: string; body: string; candidate_email: string | null; has_email: boolean } | null>(null);
  const [notifyDraftLoading, setNotifyDraftLoading] = useState(false);
  const [verification, setVerification] = useState<VerificationResult | null>(null);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [githubOverride, setGithubOverride] = useState("");
  const [myTeams, setMyTeams] = useState<Team[]>([]);
  const [comments, setComments] = useState<ReportComment[]>([]);
  const [newComment, setNewComment] = useState("");
  const [postingComment, setPostingComment] = useState(false);
  const [votesResult, setVotesResult] = useState<VotesResult | null>(null);
  const [discussLoading, setDiscussLoading] = useState(false);
  const [discussError, setDiscussError] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  // Co-Pilot state
  const [copilotLoading, setCopilotLoading] = useState(false);
  const [copilotSaving, setCopilotSaving] = useState(false);
  const [copilotSuccess, setCopilotSuccess] = useState(false);
  const [copilotError, setCopilotError] = useState<string | null>(null);
  const [scorecard, setScorecard] = useState<Array<{ category: string; label: string; score: number; notes: string }>>([
    { category: "technical", label: "Technical Depth & Architecture", score: 0, notes: "" },
    { category: "problem_solving", label: "Problem Solving & Analytical Thinking", score: 0, notes: "" },
    { category: "culture_fit", label: "Culture Fit & Communication", score: 0, notes: "" },
    { category: "authenticity", label: "Authenticity & Grounding", score: 0, notes: "" },
  ]);
  const [copilotQuestions, setCopilotQuestions] = useState<Array<{ question: string; category?: string; is_asked: boolean }>>([]);
  const [newProbeQuestion, setNewProbeQuestion] = useState("");
  const [interviewNotes, setInterviewNotes] = useState("");
  const [copilotRecOverride, setCopilotRecOverride] = useState<Decision | null>(null);

  useEffect(() => {
    if (sessionChecked && !token) { router.replace("/login"); return; }
  }, [sessionChecked, token, router]);

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

  // Load any verification that was already run for this report (silent — 404 just means "not run yet")
  useEffect(() => {
    if (!token || !params.id) return;
    (async () => {
      try {
        const v = await verifyAPI.get(params.id, token);
        setVerification(v);
      } catch {
        // No verification yet — that's expected, not an error state.
      }
    })();
  }, [params.id, token]);

  const submitDecision = useCallback(async (d: Decision) => {
    if (!token || !params.id) return;
    const previous = decision;
    setDecision(d);
    setSaving(true);
    setNotifyState("idle");
    setNotifyMessage(null);
    try {
      await reportsAPI.decision(params.id, d, undefined, token);
    } catch (e) {
      // Revert the optimistic UI update — a decision that silently failed
      // to save must not be shown as "recorded".
      setDecision(previous);
      setNotifyMessage(e instanceof APIError ? e.message : "Could not save decision. Please try again.");
    }
    setSaving(false);
  }, [token, params.id, decision]);

  // One-click send: fetches the default template and immediately emails it.
  // This never opens the editor — for that, use openNotifyEditor() below.
  const sendDefaultNotification = useCallback(async () => {
    if (!token || !params.id || !decision) return;
    setNotifyState("sending");
    setNotifyMessage(null);
    try {
      const draft = await reportsAPI.notifyDraft(params.id, decision, token);
      if (!draft.has_email || !draft.candidate_email) {
        setNotifyState("error");
        setNotifyMessage("No email address found for this candidate. Use Edit to add one manually.");
        return;
      }
      const result = await reportsAPI.notify(params.id, decision, draft.subject, draft.body, token);
      if (result.email_sent) {
        setNotifyState("sent");
        setNotifyMessage(`Email sent to ${result.candidate_email}.`);
      } else {
        setNotifyState("error");
        setNotifyMessage(result.message);
      }
    } catch (e) {
      setNotifyState("error");
      setNotifyMessage(e instanceof APIError ? e.message : "Could not send email. Please try again.");
    }
  }, [token, params.id, decision]);

  // Opens the edit-before-sending panel, pre-filled with the default draft.
  const openNotifyEditor = useCallback(async () => {
    if (!token || !params.id || !decision) return;
    setNotifyDraftLoading(true);
    setNotifyMessage(null);
    try {
      const draft = await reportsAPI.notifyDraft(params.id, decision, token);
      setNotifyDraft(draft);
      setNotifyEditorOpen(true);
    } catch (e) {
      setNotifyState("error");
      setNotifyMessage(e instanceof APIError ? e.message : "Could not load email draft.");
    }
    setNotifyDraftLoading(false);
  }, [token, params.id, decision]);

  const sendEditedNotification = useCallback(async () => {
    if (!token || !params.id || !decision || !notifyDraft) return;
    setNotifyState("sending");
    setNotifyMessage(null);
    try {
      const result = await reportsAPI.notify(params.id, decision, notifyDraft.subject, notifyDraft.body, token);
      if (result.email_sent) {
        setNotifyState("sent");
        setNotifyMessage(`Email sent to ${result.candidate_email}.`);
        setNotifyEditorOpen(false);
      } else {
        setNotifyState("error");
        setNotifyMessage(result.message);
      }
    } catch (e) {
      setNotifyState("error");
      setNotifyMessage(e instanceof APIError ? e.message : "Could not send email. Please try again.");
    }
  }, [token, params.id, decision, notifyDraft]);

  const runVerification = useCallback(async () => {
    if (!token || !params.id) return;
    setVerifyLoading(true);
    setVerifyError(null);
    try {
      const v = await verifyAPI.run(params.id, githubOverride.trim() || undefined, token);
      setVerification(v);
      if (v.recommendation_update) {
        const update = v.recommendation_update;
        setReport((prev) => prev ? {
          ...prev,
          credibility: {
            ...prev.credibility,
            recommendation: update.new_recommendation,
            ai_recommendation: update.ai_recommendation,
            recommendation_adjusted_by_verification: true,
            recommendation_adjustment_reason: update.reason,
          },
        } : prev);
      }
    } catch (e) {
      setVerifyError(e instanceof APIError ? e.message : "Verification failed. Please try again.");
    } finally {
      setVerifyLoading(false);
    }
  }, [token, params.id, githubOverride]);

  const loadDiscussData = useCallback(async () => {
    if (!token || !params.id) return;
    setDiscussLoading(true);
    setDiscussError(null);
    try {
      const [commentsRes, votesRes, teamsRes] = await Promise.all([
        collaborationAPI.listComments(params.id, token),
        collaborationAPI.listVotes(params.id, token),
        teamsAPI.list(token).catch(() => ({ teams: [] })),
      ]);
      setComments(commentsRes.comments);
      setVotesResult(votesRes);
      setMyTeams(teamsRes.teams);
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not load discussion.");
    } finally {
      setDiscussLoading(false);
    }
  }, [token, params.id]);

  const postComment = useCallback(async () => {
    if (!token || !params.id || !newComment.trim()) return;
    setPostingComment(true);
    try {
      const c = await collaborationAPI.addComment(params.id, newComment.trim(), token);
      setComments((prev) => [...prev, c]);
      setNewComment("");
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not post comment.");
    } finally {
      setPostingComment(false);
    }
  }, [token, params.id, newComment]);

  const removeComment = useCallback(async (commentId: string) => {
    if (!token || !params.id) return;
    try {
      await collaborationAPI.deleteComment(params.id, commentId, token);
      setComments((prev) => prev.filter((c) => c.id !== commentId));
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not delete comment.");
    }
  }, [token, params.id]);

  const castVote = useCallback(async (vote: "advance" | "reject" | "maybe") => {
    if (!token || !params.id) return;
    try {
      await collaborationAPI.vote(params.id, vote, token);
      const votesRes = await collaborationAPI.listVotes(params.id, token);
      setVotesResult(votesRes);
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not record vote.");
    }
  }, [token, params.id]);

  const shareWithTeam = useCallback(async (teamId: string) => {
    if (!token || !params.id) return;
    setSharing(true);
    try {
      await collaborationAPI.share(params.id, teamId, token);
      setReport((prev) => prev ? { ...prev, team_id: teamId } as Report : prev);
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not share report.");
    } finally {
      setSharing(false);
    }
  }, [token, params.id]);

  useEffect(() => {
    if (tab === "discuss") loadDiscussData();
  }, [tab, loadDiscussData]);

  const loadCopilotData = useCallback(async () => {
    if (!token || !params.id) return;
    setCopilotLoading(true);
    setCopilotError(null);
    try {
      const res = await copilotAPI.get(params.id, token);
      if (res && res.copilot) {
        const c = res.copilot;
        if (Array.isArray(c.scorecard) && c.scorecard.length > 0) {
          setScorecard(prev => prev.map(item => {
            const found = c.scorecard.find((s: any) => s.category === item.category);
            return found ? { ...item, score: found.score, notes: found.notes || "" } : item;
          }));
        }
        if (Array.isArray(c.custom_questions) && c.custom_questions.length > 0) {
          setCopilotQuestions(c.custom_questions);
        } else if (report?.interview_questions?.length) {
          setCopilotQuestions(report.interview_questions.map(q => ({ question: q.question, category: q.category, is_asked: false })));
        }
        if (c.interview_notes) setInterviewNotes(c.interview_notes);
        if (c.recommendation_override) setCopilotRecOverride(c.recommendation_override);
      } else if (report?.interview_questions?.length) {
        setCopilotQuestions(report.interview_questions.map(q => ({ question: q.question, category: q.category, is_asked: false })));
      }
    } catch {
      if (report?.interview_questions?.length) {
        setCopilotQuestions(report.interview_questions.map(q => ({ question: q.question, category: q.category, is_asked: false })));
      }
    } finally {
      setCopilotLoading(false);
    }
  }, [token, params.id, report]);

  useEffect(() => {
    if (tab === "copilot") {
      loadCopilotData();
    }
  }, [tab, loadCopilotData]);

  const saveCopilotData = async () => {
    if (!token || !params.id) return;
    setCopilotSaving(true);
    setCopilotError(null);
    setCopilotSuccess(false);
    try {
      const payload = {
        scorecard: scorecard.map(s => ({ category: s.category, score: s.score, notes: s.notes })),
        custom_questions: copilotQuestions,
        interview_notes: interviewNotes,
        recommendation_override: copilotRecOverride || decision || undefined,
      };
      await copilotAPI.save(params.id, payload, token);
      setCopilotSuccess(true);
      setTimeout(() => setCopilotSuccess(false), 3500);
    } catch (e) {
      setCopilotError(e instanceof APIError ? e.message : "Failed to save evaluation scorecard.");
    } finally {
      setCopilotSaving(false);
    }
  };

  if (loading) return (
    <div style={{ minHeight: "100vh", background: "#12141A", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: "#B4B4AC", fontSize: 14 }}>Loading report…</div>
    </div>
  );

  if (error || !report) return (
    <div style={{ minHeight: "100vh", background: "#12141A", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16 }}>
      <div style={{ color: "#B3543A", fontSize: 14 }}>{error || "Report not found."}</div>
      <Link href="/dashboard" style={{ color: "#5FA39D", fontSize: 13 }}>← Back to Dashboard</Link>
    </div>
  );

  const cred     = report.credibility || {} as any;
  const scores   = cred.sub_scores || {} as any;
  const rationale = cred.score_rationale || {} as any;
  const flags    = report.flags || [];
  const highFlags = flags.filter(f => f.severity === "high").length;

  const TABS = [
    { id: "overview",   label: "Overview" },
    { id: "copilot",    label: "Interview Co-Pilot" },
    { id: "flags",      label: `Flags (${flags.length})` },
    { id: "skills",     label: "Skills" },
    { id: "timeline",   label: "Timeline" },
    { id: "verify",     label: "Verify" },
    { id: "discuss",    label: "Discuss" },
    { id: "questions",  label: "Interview Qs" },
    { id: "json",       label: "JSON" },
  ];


  return (
    <div style={{ minHeight: "100vh", background: "#12141A", color: "#EDEDEA" }}>
      <style>{`@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}.fu{animation:fadeUp .3s ease}`}</style>

      {/* Navbar */}
      <nav style={{
        height: 60, borderBottom: "1px solid #2A2D37",
        display: "flex", alignItems: "center", paddingInline: 28, gap: 16,
        position: "sticky", top: 0, background: "#12141A", zIndex: 100
      }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 9, textDecoration: "none" }}>
          <div style={{
            width: 26, height: 26, borderRadius: 6,
            background: "#3B7D78",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}><Search size={14} color="#F5F5F2" strokeWidth={2.5} /></div>
          <span className="font-display" style={{ fontWeight: 600, fontSize: 17, color: "#EDEDEA" }}>HireLens</span>
        </Link>
        <span style={{ color: "#383C48" }}>|</span>
        <span style={{ fontSize: 13, color: "#B4B4AC" }}>Candidate Intelligence Report</span>
        <div style={{ flex: 1 }} />
        <Link href="/analyze" style={{ padding: "7px 16px", borderRadius: 6, background: "#3B7D78", color: "#F5F5F2", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>
          + New Analysis
        </Link>
      </nav>

      <div style={{ maxWidth: 980, margin: "0 auto", padding: "24px 20px 80px" }}>
        <Link href="/dashboard" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "#5FA39D", textDecoration: "none", marginBottom: 20, fontWeight: 600 }}>
          ← Back to Dashboard
        </Link>

        {/* Header card */}
        <div className="fu" style={{
          background: "#191B22",
          border: "1px solid #2A2D37", borderRadius: 10,
          overflow: "hidden", marginBottom: 16
        }}>

          {/* Docket strip */}
          <div style={{ padding: "10px 28px", borderBottom: "1px solid rgba(237, 237, 234, 0.08)", display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(18, 20, 26, 0.7)" }}>
            <span className="font-mono" style={{ fontSize: 11, color: "#B4B4AC", letterSpacing: 0.3, fontWeight: 600 }}>
              Candidate Intelligence File · {report.id ? report.id.slice(0, 8) : "—"}
            </span>
            <span className="font-mono" style={{ fontSize: 11, color: "#B4B4AC", letterSpacing: 0.3 }}>
              Examined {report.created_at ? new Date(report.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—"}
            </span>
          </div>

          {cred.recommendation_adjusted_by_verification && (
            <div style={{ padding: "12px 28px", background: "rgba(179, 84, 58, 0.1)", borderBottom: "1px solid rgba(179, 84, 58, 0.25)", display: "flex", alignItems: "center", gap: 8 }}>
              <AlertTriangle size={14} color="#B3543A" style={{ flexShrink: 0 }} />
              <span style={{ fontSize: 12, color: "#B3543A", fontWeight: 600 }}>
                Recommendation adjusted from &quot;{cred.ai_recommendation}&quot; after verification —
              </span>
              <span style={{ fontSize: 12, color: "#EDEDEA" }}> {cred.recommendation_adjustment_reason}</span>
            </div>
          )}

          {/* Top section */}
          <div style={{ padding: "24px 28px", borderBottom: "1px solid rgba(237, 237, 234, 0.08)", display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
            <ScoreDocket score={cred.overall || 0} verdict={verdictFromRecommendation(cred.recommendation || "manual_review")} />
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <h2 style={{ margin: 0, fontSize: 26, fontWeight: 600, color: "#EDEDEA", letterSpacing: -0.5 }}>
                  {report.candidate?.name || "Unknown Candidate"}
                </h2>
                {highFlags > 0 && (
                  <span style={{ padding: "3px 10px", borderRadius: 10, fontSize: 11, fontWeight: 600, color: "#B3543A", background: "rgba(179, 84, 58, 0.15)", border: "1px solid rgba(179, 84, 58, 0.3)" }}>
                    {highFlags} high-risk flag{highFlags > 1 ? "s" : ""}
                  </span>
                )}
              </div>
              {report.candidate?.current_role && (
                <div style={{ fontSize: 14, color: "#5FA39D", fontWeight: 600, marginBottom: 6 }}>{report.candidate.current_role}</div>
              )}
              <div style={{ fontSize: 13, color: "#B4B4AC", marginBottom: 14, lineHeight: 1.6 }}>
                {[report.candidate?.email, report.candidate?.phone, report.candidate?.location].filter(Boolean).join("  ·  ") || "Contact info not found in resume"}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {(report.skills?.all_claimed || []).slice(0, 8).map(s => {
                  const v = (report.skills?.verified_by_evidence || []).includes(s);
                  return (
                    <span key={s} style={{ padding: "4px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600, color: v ? "#5C9A6C" : "#B98A3E", background: v ? "rgba(92,154,108,0.15)" : "rgba(185,138,62,0.15)", border: `1px solid ${v ? "rgba(92,154,108,0.3)" : "rgba(185,138,62,0.3)"}`, display: "inline-flex", alignItems: "center", gap: 5 }}>
                      {v ? <Check size={11} strokeWidth={3} /> : <span style={{ fontWeight: 600 }}>?</span>}
                      <span>{s}</span>
                    </span>
                  );
                })}
                {(report.skills?.all_claimed?.length || 0) > 8 && (
                  <span style={{ fontSize: 12, color: "#B4B4AC", alignSelf: "center", fontWeight: 500 }}>
                    +{(report.skills?.all_claimed?.length || 0) - 8} more
                  </span>
                )}
              </div>
            </div>
            <div style={{ flexShrink: 0, textAlign: "right" }}>
              <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 12, color: "#B4B4AC", marginBottom: 4 }}>{report.file_name}</div>
              <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 12, color: "#8A8B82" }}>
                {report.created_at ? new Date(report.created_at).toLocaleDateString() : "Just analyzed"}
              </div>
            </div>
          </div>

          {/* One-liner */}
          {report.one_liner && (
            <div style={{ padding: "12px 28px", background: "rgba(59, 125, 120, 0.08)", borderBottom: "1px solid rgba(237, 237, 234, 0.08)" }}>
              <span style={{ fontSize: 14, color: "#CBD5E1", fontStyle: "italic", fontWeight: 500 }}>&ldquo;{report.one_liner}&rdquo;</span>
            </div>
          )}

          {/* Tabs */}
          <div style={{ display: "flex", borderBottom: "1px solid rgba(237, 237, 234, 0.08)", overflowX: "auto", background: "rgba(18, 20, 26, 0.4)" }}>
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)} style={{
                padding: "14px 20px", background: "none", border: "none", cursor: "pointer",
                fontFamily: "inherit", color: tab === t.id ? "#EDEDEA" : "#B4B4AC",
                borderBottom: `2px solid ${tab === t.id ? "#3B7D78" : "transparent"}`,
                fontWeight: tab === t.id ? 700 : 500, fontSize: 13, whiteSpace: "nowrap", transition: "all 0.15s ease"
              }}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div style={{ padding: "28px 28px" }}>

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
                    <ScoreBar label="Content Authenticity" value={scores.content_authenticity ?? 70} rationale={rationale.content_authenticity} />
                  </div>
                </div>
                <div style={{ fontSize: 12, color: "#B4B4AC", marginTop: -12, marginBottom: 20 }}>ⓘ Hover score labels to view detailed AI rationale</div>

                {/* AI-Generated Content Detection — core feature */}
                {report.ai_content_analysis && (
                  <AIContentCard analysis={report.ai_content_analysis} />
                )}

                {/* Feature B: Predictive Talent Velocity & Career Growth Index */}
                {report.talent_velocity && (
                  <div style={{ background: "rgba(59, 125, 120, 0.06)", border: "1px solid rgba(59, 125, 120, 0.25)", borderRadius: 10, padding: "20px 24px", marginBottom: 20 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                      <div style={{ fontSize: 11, color: "#5FA39D", fontWeight: 600, letterSpacing: 0.3 }}>
                        Predictive Career Growth & Talent Velocity
                      </div>
                      <span style={{ padding: "4px 12px", borderRadius: 99, background: "rgba(59, 125, 120, 0.2)", border: "1px solid rgba(59, 125, 120, 0.4)", color: "#5FA39D", fontSize: 11, fontWeight: 600 }}>
                        {report.talent_velocity.trajectory_stage}
                      </span>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 12 }}>
                      <div style={{ background: "rgba(18, 20, 26, 0.6)", padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(237, 237, 234, 0.05)" }}>
                        <div style={{ fontSize: 11, color: "#B4B4AC" }}>Growth Index</div>
                        <div style={{ fontSize: 24, fontWeight: 600, color: "#3B7D78", fontFamily: "var(--font-mono), monospace" }}>{report.talent_velocity.growth_velocity_index}/100</div>
                      </div>
                      <div style={{ background: "rgba(18, 20, 26, 0.6)", padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(237, 237, 234, 0.05)" }}>
                        <div style={{ fontSize: 11, color: "#B4B4AC" }}>Promotion Cadence</div>
                        <div style={{ fontSize: 24, fontWeight: 600, color: "#5C9A6C", fontFamily: "var(--font-mono), monospace" }}>~{report.talent_velocity.promotion_cadence_months} mos</div>
                      </div>
                      <div style={{ background: "rgba(18, 20, 26, 0.6)", padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(237, 237, 234, 0.05)" }}>
                        <div style={{ fontSize: 11, color: "#B4B4AC" }}>Retention Stability</div>
                        <div style={{ fontSize: 24, fontWeight: 600, color: "#5B84A6", fontFamily: "var(--font-mono), monospace" }}>{report.talent_velocity.retention_stability_score}%</div>
                      </div>
                    </div>
                    <div style={{ fontSize: 12, color: "#CBD5E1", lineHeight: 1.5 }}>
                      {report.talent_velocity.note}
                    </div>
                  </div>
                )}

                {/* Summary */}

                <div style={{ background: "rgba(18, 20, 26, 0.6)", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 10, padding: "20px 24px", marginBottom: 18 }}>
                  <div style={{ fontSize: 11, color: "#5FA39D", fontWeight: 600, letterSpacing: 0.3, marginBottom: 10 }}>AI Recruiter Summary</div>
                  <p style={{ fontSize: 14, color: "#CBD5E1", lineHeight: 1.75, margin: 0 }}>{report.summary}</p>
                </div>

                {/* Positives */}
                {(report.positive_signals || []).length > 0 && (
                  <div style={{ background: "rgba(92, 154, 108, 0.08)", border: "1px solid rgba(92, 154, 108, 0.25)", borderRadius: 10, padding: "20px 24px" }}>
                    <div style={{ fontSize: 11, color: "#5C9A6C", fontWeight: 600, letterSpacing: 0.3, marginBottom: 12 }}>Positive Signals</div>
                    {report.positive_signals!.map((p, i) => (
                      <div key={i} style={{ display: "flex", gap: 10, marginBottom: 8, alignItems: "flex-start" }}>
                        <Check size={14} color="#5C9A6C" strokeWidth={3} style={{ flexShrink: 0, marginTop: 2 }} />
                        <div style={{ fontSize: 13, color: "#CBD5E1" }}><strong style={{ color: "#EDEDEA" }}>{p.title}:</strong> {p.description}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* INTERVIEW CO-PILOT — Live candidate evaluation & scorecard */}
            {tab === "copilot" && (
              <div className="fu">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: "#EDEDEA" }}>Live Interview Co-Pilot & Candidate Scorecard</h3>
                    <p style={{ margin: "4px 0 0", fontSize: 13, color: "#B4B4AC" }}>
                      Rate candidate competency, check off probe questions during live interviews, and store structured feedback.
                    </p>
                  </div>
                  <button
                    onClick={saveCopilotData}
                    disabled={copilotSaving}
                    style={{
                      padding: "9px 20px", borderRadius: 10,
                      background: copilotSuccess ? "#5C9A6C" : "linear-gradient(135deg, #3B7D78, #2A5D59)",
                      color: "#FFF", fontWeight: 600, fontSize: 13, border: "none", cursor: "pointer",
                      boxShadow: "0 4px 14px rgba(59,125,120,0.3)", display: "flex", alignItems: "center", gap: 6
                    }}
                  >
                    {copilotSaving ? "Saving…" : copilotSuccess ? "Scorecard Saved" : "Save Evaluation"}
                  </button>
                </div>

                {copilotError && (
                  <div style={{ padding: "10px 14px", background: "rgba(179,84,58,0.1)", border: "1px solid rgba(179,84,58,0.3)", borderRadius: 10, fontSize: 12, color: "#B3543A", marginBottom: 16 }}>
                    {copilotError}
                  </div>
                )}

                {copilotLoading ? (
                  <div style={{ fontSize: 13, color: "#B4B4AC", padding: 24, textAlign: "center" }}>Loading interview scorecard…</div>
                ) : (
                  <>
                    {/* Scorecard Dimensions */}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16, marginBottom: 24 }}>
                      {scorecard.map((item, idx) => (
                        <div key={item.category} style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8, padding: "16px 18px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                            <span style={{ fontSize: 13, fontWeight: 600, color: "#EDEDEA" }}>{item.label}</span>
                            <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: 13, fontWeight: 600, color: item.score > 0 ? (item.score >= 4 ? "#5C9A6C" : item.score >= 3 ? "#B98A3E" : "#B3543A") : "#8A8B82" }}>
                              {item.score > 0 ? `${item.score} / 5` : "Unrated"}
                            </span>
                          </div>
                          
                          {/* Rating chips 1 to 5 */}
                          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                            {[1, 2, 3, 4, 5].map(star => {
                              const active = item.score === star;
                              return (
                                <button
                                  key={star}
                                  type="button"
                                  onClick={() => {
                                    setScorecard(prev => prev.map((s, i) => i === idx ? { ...s, score: star } : s));
                                  }}
                                  style={{
                                    flex: 1, padding: "6px 0", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer",
                                    border: active ? "1px solid #3B7D78" : "1px solid rgba(237, 237, 234, 0.08)",
                                    background: active ? "rgba(59, 125, 120, 0.3)" : "rgba(18, 20, 26, 0.6)",
                                    color: active ? "#5FA39D" : "#B4B4AC", transition: "all 0.15s",
                                    display: "flex", alignItems: "center", justifyContent: "center", gap: 4
                                  }}
                                >
                                  <Star size={11} fill={active ? "#5FA39D" : "none"} strokeWidth={2} />
                                  <span>{star}</span>
                                </button>
                              );
                            })}
                          </div>

                          <input
                            type="text"
                            placeholder="Interviewer observations/notes…"
                            value={item.notes}
                            onChange={(e) => {
                              const val = e.target.value;
                              setScorecard(prev => prev.map((s, i) => i === idx ? { ...s, notes: val } : s));
                            }}
                            style={{
                              width: "100%", boxSizing: "border-box", padding: "7px 10px", borderRadius: 6,
                              background: "rgba(18, 20, 26, 0.6)", border: "1px solid rgba(237, 237, 234, 0.06)",
                              color: "#EDEDEA", fontSize: 12, outline: "none"
                            }}
                          />
                        </div>
                      ))}
                    </div>

                    {/* Probing Questions Checklist */}
                    <div style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8, padding: "20px 22px", marginBottom: 24 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#B4B4AC", letterSpacing: 0.5, marginBottom: 12 }}>
                        Live Question Checklist ({copilotQuestions.filter(q => q.is_asked).length}/{copilotQuestions.length} Asked)
                      </div>
                      
                      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
                        {copilotQuestions.map((q, qIdx) => (
                          <div
                            key={qIdx}
                            onClick={() => {
                              setCopilotQuestions(prev => prev.map((item, i) => i === qIdx ? { ...item, is_asked: !item.is_asked } : item));
                            }}
                            style={{
                              display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 14px",
                              background: q.is_asked ? "rgba(92, 154, 108, 0.06)" : "rgba(18, 20, 26, 0.5)",
                              border: q.is_asked ? "1px solid rgba(92, 154, 108, 0.3)" : "1px solid rgba(237, 237, 234, 0.06)",
                              borderRadius: 8, cursor: "pointer", transition: "all 0.15s"
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={q.is_asked}
                              readOnly
                              style={{ marginTop: 3, cursor: "pointer", accentColor: "#5C9A6C" }}
                            />
                            <div style={{ flex: 1 }}>
                              <span style={{ fontSize: 13, color: q.is_asked ? "#B4B4AC" : "#EDEDEA", textDecoration: q.is_asked ? "line-through" : "none", lineHeight: 1.5 }}>
                                {q.question}
                              </span>
                              {q.category && (
                                <span style={{ marginLeft: 8, fontSize: 10, color: "#5FA39D", background: "rgba(59,125,120,0.15)", padding: "2px 6px", borderRadius: 4 }}>
                                  {q.category}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>

                      {/* Add Custom Question on the fly */}
                      <div style={{ display: "flex", gap: 10 }}>
                        <input
                          type="text"
                          placeholder="Add custom interview question on the fly…"
                          value={newProbeQuestion}
                          onChange={(e) => setNewProbeQuestion(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && newProbeQuestion.trim()) {
                              setCopilotQuestions(prev => [...prev, { question: newProbeQuestion.trim(), category: "custom", is_asked: false }]);
                              setNewProbeQuestion("");
                            }
                          }}
                          style={{
                            flex: 1, padding: "9px 14px", background: "rgba(18, 20, 26, 0.6)",
                            border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8,
                            color: "#EDEDEA", fontSize: 13, outline: "none"
                          }}
                        />
                        <button
                          type="button"
                          disabled={!newProbeQuestion.trim()}
                          onClick={() => {
                            if (newProbeQuestion.trim()) {
                              setCopilotQuestions(prev => [...prev, { question: newProbeQuestion.trim(), category: "custom", is_asked: false }]);
                              setNewProbeQuestion("");
                            }
                          }}
                          style={{
                            padding: "9px 18px", borderRadius: 8, background: "rgba(59, 125, 120, 0.2)",
                            border: "1px solid rgba(59, 125, 120, 0.4)", color: "#5FA39D", fontSize: 13, fontWeight: 600, cursor: "pointer"
                          }}
                        >
                          + Add Question
                        </button>
                      </div>
                    </div>

                    {/* General Interview Notes & Override */}
                    <div style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8, padding: "20px 22px" }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#B4B4AC", letterSpacing: 0.5, marginBottom: 10 }}>
                        Interviewer Feedback & Recommendation
                      </div>
                      <textarea
                        rows={4}
                        value={interviewNotes}
                        onChange={(e) => setInterviewNotes(e.target.value)}
                        placeholder="Candidate live demonstration feedback, communication clarity, coding walkthrough observations…"
                        style={{
                          width: "100%", boxSizing: "border-box", padding: "12px 14px", background: "rgba(18, 20, 26, 0.6)",
                          border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 10, color: "#EDEDEA", fontSize: 13,
                          fontFamily: "inherit", outline: "none", resize: "vertical", marginBottom: 16
                        }}
                      />

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <span style={{ fontSize: 12, color: "#B4B4AC", marginRight: 4 }}>Verdict:</span>
                          {([
                            { val: "advance", label: "Advance", color: "#5C9A6C" },
                            { val: "schedule_followup", label: "Follow-up", color: "#B98A3E" },
                            { val: "reject", label: "Reject", color: "#B3543A" },
                          ] as const).map(o => (
                            <button
                              key={o.val}
                              type="button"
                              onClick={() => setCopilotRecOverride(o.val)}
                              style={{
                                padding: "6px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer",
                                border: `1px solid ${o.color}`,
                                background: copilotRecOverride === o.val ? `${o.color}22` : "transparent",
                                color: o.color
                              }}
                            >
                              {o.label}
                            </button>
                          ))}
                        </div>

                        <button
                          onClick={saveCopilotData}
                          disabled={copilotSaving}
                          style={{
                            padding: "9px 24px", borderRadius: 8, background: "#5B84A6", color: "#FFF",
                            fontWeight: 600, fontSize: 13, border: "none", cursor: "pointer"
                          }}
                        >
                          {copilotSaving ? "Saving…" : "Save Evaluation"}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* FLAGS */}
            {tab === "flags" && (
              <div className="fu">
                {flags.length === 0 ? (
                  <div style={{ textAlign: "center", padding: 40 }}>
                    <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
                      <CheckCircle2 size={36} color="#5C9A6C" />
                    </div>
                    <div style={{ fontSize: 14, color: "#5C9A6C", fontWeight: 600 }}>No significant risk flags detected</div>
                    <div style={{ fontSize: 12, color: "#B4B4AC", marginTop: 6 }}>Resume appears consistent and well-evidenced.</div>
                  </div>
                ) : (
                  <>
                    <div style={{ fontSize: 12, color: "#B4B4AC", marginBottom: 14 }}>
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
                  <div style={{ marginBottom: 16, padding: "12px 16px", background: "rgba(91,132,166,.1)", border: "1px solid rgba(91,132,166,.25)", borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <span style={{ fontSize: 12, color: "#5B84A6" }}>Primary domain: </span>
                      <strong style={{ fontSize: 12, color: "#EDEDEA" }}>{report.skills.primary_domain}</strong>
                    </div>
                    {report.skills.keyword_stuffing_risk && report.skills.keyword_stuffing_risk !== "none" && (
                      <span style={{ fontSize: 11, color: "#B98A3E", display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <AlertTriangle size={12} color="#B98A3E" /> Keyword stuffing risk: {report.skills.keyword_stuffing_risk}
                      </span>
                    )}
                  </div>
                )}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 10, color: "#8A8B82", letterSpacing: 0.3, marginBottom: 12 }}>All Skills — Verification Status</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {(report.skills?.all_claimed || []).map(s => {
                      const v = (report.skills?.verified_by_evidence || []).includes(s);
                      return (
                        <span key={s} style={{ padding: "6px 13px", borderRadius: 9, fontSize: 12, fontWeight: 600, color: v ? "#5C9A6C" : "#B98A3E", background: v ? "rgba(92,154,108,.1)" : "rgba(185,138,62,.1)", border: `1px solid ${v ? "#5C9A6C" : "#B98A3E"}33`, display: "inline-flex", alignItems: "center", gap: 6 }}>
                          {v ? <Check size={12} strokeWidth={3} /> : <span style={{ fontWeight: 600 }}>?</span>}
                          <span>{s}</span>
                        </span>
                      );
                    })}
                  </div>
                  <div style={{ fontSize: 11, color: "#8A8B82", marginTop: 10 }}>Evidenced in work history: confirmed · Unconfirmed: listed only in summary</div>
                </div>
                {(report.skills?.domain_spread_concern) && (
                  <div style={{ padding: "14px 16px", background: "rgba(185,138,62,.08)", border: "1px solid rgba(185,138,62,.2)", borderRadius: 10 }}>
                    <div style={{ fontSize: 11, color: "#B98A3E", fontWeight: 600, marginBottom: 6 }}>DOMAIN SPREAD CONCERN</div>
                    <div style={{ fontSize: 12, color: "#CBD5E1" }}>{report.skills.domain_spread_note}</div>
                  </div>
                )}
              </div>
            )}

            {/* TIMELINE */}
            {tab === "timeline" && (
              <div className="fu">
                {(report.timeline_gaps || []).length > 0 && (
                  <div style={{ marginBottom: 20, padding: "14px 16px", background: "rgba(185,138,62,.08)", border: "1px solid rgba(185,138,62,.2)", borderRadius: 10 }}>
                    <div style={{ fontSize: 11, color: "#B98A3E", fontWeight: 600, marginBottom: 8 }}>GAPS DETECTED</div>
                    {report.timeline_gaps!.map((g, i) => (
                      <div key={i} style={{ fontSize: 12, color: "#CBD5E1", marginBottom: 5 }}>
                        {g.from} → {g.to}: <strong>{g.duration}</strong> ·{" "}
                        <span style={{ color: g.severity === "high" ? "#B3543A" : g.severity === "medium" ? "#B98A3E" : "#5B84A6" }}>{g.severity} severity</span>
                        {g.note && <span style={{ color: "#B4B4AC" }}> — {g.note}</span>}
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {(report.experience || []).map((exp, i) => (
                    <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                        <div style={{ width: 10, height: 10, borderRadius: "50%", marginTop: 4, background: exp.is_verifiable !== false ? "#5B84A6" : "#B98A3E", boxShadow: `0 0 0 3px ${exp.is_verifiable !== false ? "#5B84A6" : "#B98A3E"}33` }} />
                        {i < (report.experience || []).length - 1 && <div style={{ width: 2, flex: 1, background: "rgba(237, 237, 234, 0.08)", minHeight: 32, marginTop: 4 }} />}
                      </div>
                      <div style={{ paddingBottom: i < (report.experience || []).length - 1 ? 20 : 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "#EDEDEA" }}>{exp.role}</div>
                        <div style={{ fontSize: 12, color: exp.is_verifiable !== false ? "#5B84A6" : "#B98A3E" }}>{exp.company}</div>
                        <div style={{ fontSize: 11, color: "#B4B4AC", marginTop: 2 }}>{exp.period}</div>
                        {exp.is_verifiable === false && (
                          <div style={{ fontSize: 11, color: "#B98A3E", marginTop: 2, display: "flex", alignItems: "center", gap: 4 }}>
                            <AlertTriangle size={11} color="#B98A3E" /> Company not easily verifiable
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {(report.education || []).length > 0 && (
                  <div style={{ marginTop: 24 }}>
                    <div style={{ fontSize: 10, color: "#8A8B82", letterSpacing: 0.3, marginBottom: 14 }}>Education</div>
                    {report.education!.map((e, i) => (
                      <div key={i} style={{ padding: "12px 16px", background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 10, marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "#EDEDEA" }}>{e.degree}</div>
                        <div style={{ fontSize: 12, color: e.is_recognized_institution !== false ? "#5B84A6" : "#B98A3E" }}>{e.institution}</div>
                        <div style={{ fontSize: 11, color: "#B4B4AC" }}>{e.period}</div>
                        {e.concern && (
                          <div style={{ fontSize: 11, color: "#B98A3E", marginTop: 4, display: "flex", alignItems: "center", gap: 4 }}>
                            <AlertTriangle size={11} color="#B98A3E" /> {e.concern}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* VERIFY — Feature 3: real-time public data verification */}
            {tab === "verify" && (
              <div className="fu">
                <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
                  <div style={{ flex: "1 1 220px" }}>
                    <label style={{ fontSize: 11, fontWeight: 600, color: "#B4B4AC", display: "block", marginBottom: 6 }}>
                      GitHub username (optional override)
                    </label>
                    <input
                      value={githubOverride}
                      onChange={(e) => setGithubOverride(e.target.value)}
                      placeholder={report.candidate?.github ? "Found on resume — leave blank to use it" : "e.g. octocat"}
                      style={{
                        width: "100%", boxSizing: "border-box", padding: "9px 12px", background: "#191B22",
                        border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 9, color: "#EDEDEA", fontSize: 13,
                        fontFamily: "inherit", outline: "none",
                      }}
                    />
                  </div>
                  <button
                    onClick={runVerification}
                    disabled={verifyLoading}
                    style={{
                      padding: "10px 20px", borderRadius: 10, border: "none", cursor: verifyLoading ? "default" : "pointer",
                      background: "linear-gradient(135deg,#5B84A6,#2C4258)", color: "#EDEDEA", fontWeight: 600,
                      fontSize: 13, fontFamily: "inherit", opacity: verifyLoading ? 0.7 : 1, whiteSpace: "nowrap",
                    }}
                  >
                    {verifyLoading ? "Verifying…" : verification ? "Re-run Verification" : "Run Verification"}
                  </button>
                </div>
                <p style={{ fontSize: 11, color: "#B4B4AC", margin: "0 0 20px", lineHeight: 1.6 }}>
                  Runs live checks against GitHub, a university registry, and company websites.
                  These are corroborating signals, not proof — a &quot;not found&quot; result often means
                  the data simply isn&apos;t public, not that something is false.
                </p>

                {verifyError && (
                  <div style={{ padding: "10px 14px", background: "rgba(179,84,58,0.08)", border: "1px solid rgba(179,84,58,.3)", borderRadius: 10, fontSize: 12, color: "#B3543A", marginBottom: 16 }}>
                    {verifyError}
                  </div>
                )}

                {!verification && !verifyLoading && !verifyError && (
                  <div style={{ padding: 40, textAlign: "center", border: "1px dashed rgba(237, 237, 234, 0.08)", borderRadius: 8 }}>
                    <div style={{ display: "flex", justifyContent: "center", marginBottom: 10 }}>
                      <Search size={28} color="#8A8B82" />
                    </div>
                    <div style={{ fontSize: 13, color: "#B4B4AC" }}>No verification has been run yet for this report.</div>
                  </div>
                )}

                {verification && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ fontSize: 11, color: "#8A8B82" }}>
                      Last run: {new Date(verification.run_at).toLocaleString()}
                    </div>

                    {verification.trust_assessment && (
                      <TrustAssessmentCard trust={verification.trust_assessment} />
                    )}

                    {/* GitHub */}
                    <VerifyCard title="GitHub Skills">
                      <GithubVerifyBlock g={verification.github} />
                    </VerifyCard>

                    {/* Education */}
                    <VerifyCard title="Education">
                      {verification.education.length === 0 ? (
                        <EmptyNote text="No education entries were found on this resume to check." />
                      ) : (
                        verification.education.map((e, i) => (
                          <VerifyRow
                            key={i}
                            label={e.institution || "Unknown institution"}
                            status={e.status}
                            statusMap={EDU_STATUS_MAP}
                            detail={e.status === "verified" ? `${e.matched_name}${e.country ? " · " + e.country : ""}` : e.note}
                          />
                        ))
                      )}
                    </VerifyCard>

                    {/* Certifications */}
                    <VerifyCard title="Certifications">
                      {verification.certifications.length === 0 ? (
                        <EmptyNote text="No certifications were found on this resume to check." />
                      ) : (
                        verification.certifications.map((c, i) => (
                          <VerifyRow
                            key={i}
                            label={c.name}
                            status={c.status}
                            statusMap={CERT_STATUS_MAP}
                            detail={c.note}
                            link={c.url}
                          />
                        ))
                      )}
                    </VerifyCard>

                    {/* Employer / Experience */}
                    <VerifyCard title="Employers">
                      {verification.experience.length === 0 ? (
                        <EmptyNote text="No work experience entries were found on this resume to check." />
                      ) : (
                        verification.experience.map((x, i) => (
                          <VerifyRow
                            key={i}
                            label={x.company || "Unknown company"}
                            status={x.status}
                            statusMap={EXP_STATUS_MAP}
                            detail={x.domain_checked ? `Checked: ${x.domain_checked}` : x.note}
                          />
                        ))
                      )}
                    </VerifyCard>
                  </div>
                )}
              </div>
            )}

            {/* DISCUSS — team collaboration: share, vote, comment */}
            {tab === "discuss" && (
              <div className="fu">
                {discussError && (
                  <div style={{ padding: "10px 14px", background: "rgba(179,84,58,0.08)", border: "1px solid rgba(179,84,58,.3)", borderRadius: 6, fontSize: 12, color: "#B3543A", marginBottom: 16 }}>
                    {discussError}
                  </div>
                )}

                {/* Share with team */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#B4B4AC", marginBottom: 8, letterSpacing: 0.5 }}>Share With Team</div>
                  {myTeams.length === 0 ? (
                    <div style={{ fontSize: 12, color: "#8A8B82" }}>
                      No teams yet. <a href="/teams" style={{ color: "#5B84A6" }}>Create one</a> to share this report and collaborate.
                    </div>
                  ) : report.team_id ? (
                    <div style={{ fontSize: 12, color: "#5C9A6C", display: "flex", alignItems: "center", gap: 6 }}>
                      <Check size={13} strokeWidth={3} />
                      <span>Shared with your team — teammates can see, comment, and vote on this report.</span>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {myTeams.map((t) => (
                        <button
                          key={t.id}
                          onClick={() => shareWithTeam(t.id)}
                          disabled={sharing}
                          style={{ padding: "7px 14px", borderRadius: 6, border: "1px solid rgba(237, 237, 234, 0.08)", background: "#191B22", color: "#CBD5E1", fontSize: 12, cursor: "pointer" }}
                        >
                          Share with &quot;{t.name}&quot;
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Votes */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#B4B4AC", marginBottom: 8, letterSpacing: 0.5 }}>Team Vote</div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                    {(["advance", "maybe", "reject"] as const).map((v) => {
                      const active = votesResult?.my_vote === v;
                      const colors = { advance: "#5C9A6C", maybe: "#B98A3E", reject: "#B3543A" };
                      return (
                        <button
                          key={v}
                          onClick={() => castVote(v)}
                          style={{
                            padding: "8px 16px", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
                            border: `1.5px solid ${colors[v]}`, background: active ? `${colors[v]}22` : "transparent",
                            color: colors[v], textTransform: "capitalize",
                          }}
                        >
                          {v} {votesResult ? `(${votesResult.tally[v]})` : ""}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Comments */}
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#B4B4AC", marginBottom: 8, letterSpacing: 0.5 }}>Comments</div>
                  {discussLoading ? (
                    <div style={{ fontSize: 12, color: "#8A8B82" }}>Loading…</div>
                  ) : (
                    <>
                      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 14 }}>
                        {comments.length === 0 ? (
                          <div style={{ fontSize: 12, color: "#8A8B82" }}>No comments yet.</div>
                        ) : (
                          comments.map((c) => (
                            <div key={c.id} style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 6, padding: "10px 14px" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                <span style={{ fontSize: 11, color: "#5B84A6", fontFamily: "var(--font-mono), monospace" }}>{c.user_id.slice(0, 8)}…</span>
                                <span style={{ fontSize: 10, color: "#8A8B82" }}>{new Date(c.created_at).toLocaleString()}</span>
                              </div>
                              <p style={{ fontSize: 13, color: "#CBD5E1", margin: 0, lineHeight: 1.6 }}>{c.comment}</p>
                              <button onClick={() => removeComment(c.id)} style={{ background: "none", border: "none", color: "#8A8B82", fontSize: 11, cursor: "pointer", marginTop: 6, padding: 0 }}>Delete</button>
                            </div>
                          ))
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        <input
                          value={newComment}
                          onChange={(e) => setNewComment(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") postComment(); }}
                          placeholder="Add a comment for your team…"
                          style={{ flex: 1, padding: "9px 12px", background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 6, color: "#EDEDEA", fontSize: 13, fontFamily: "inherit", outline: "none" }}
                        />
                        <button
                          onClick={postComment}
                          disabled={postingComment || !newComment.trim()}
                          style={{ padding: "9px 18px", borderRadius: 6, border: "none", background: "#5B84A6", color: "#EDEDEA", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
                        >
                          Post
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* INTERVIEW QUESTIONS */}
            {tab === "questions" && (
              <div className="fu">
                <div style={{ fontSize: 12, color: "#B4B4AC", marginBottom: 16 }}>Generated from this candidate&apos;s specific signals — not generic templates</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {(report.interview_questions || []).map((q, i) => (
                    <div key={i} style={{ display: "flex", gap: 14, padding: "15px 18px", background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8 }}>
                      <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: 11, color: "#5B84A6", flexShrink: 0, paddingTop: 2, minWidth: 28, fontWeight: 600 }}>Q{i + 1}</span>
                      <div>
                        <div style={{ fontSize: 13, color: "#EDEDEA", lineHeight: 1.65, fontWeight: 500, marginBottom: q.rationale ? 6 : 0 }}>{q.question}</div>
                        {q.rationale && <div style={{ fontSize: 11, color: "#B4B4AC", lineHeight: 1.5 }}>↳ {q.rationale}</div>}
                        {q.targets_flag && <div style={{ fontSize: 11, color: "#B98A3E", marginTop: 3 }}>Targets: {q.targets_flag}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* RAW JSON */}
            {tab === "json" && (
              <div className="fu">
                <div style={{ fontSize: 12, color: "#B4B4AC", marginBottom: 12 }}>Full structured output — use via API for ATS/HRIS integration</div>
                <pre style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 8, padding: 18, fontSize: 10.5, color: "#B4B4AC", overflow: "auto", fontFamily: "var(--font-mono), monospace", lineHeight: 1.75, margin: 0, maxHeight: 500 }}>
                  {JSON.stringify(report, null, 2)}
                </pre>
              </div>
            )}

          </div>
        </div>

        {/* Decision panel */}
        <div className="fu" style={{ background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 10, padding: "18px 24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontSize: 10, color: "#8A8B82", letterSpacing: 0.3 }}>Recruiter Decision</div>
            <div style={{ fontSize: 11, color: "#8A8B82", fontStyle: "italic" }}>
              {saving ? "Saving…" : "Your decision trains the AI model"}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {([
              { val: "advance",           label: "Advance to Interview", color: "#5C9A6C", bg: "rgba(92,154,108,.1)",  border: "#5C9A6C" },
              { val: "schedule_followup", label: "Request More Info",    color: "#B98A3E", bg: "rgba(185,138,62,.1)", border: "#B98A3E" },
              { val: "reject",            label: "Not a Match",          color: "#B3543A", bg: "rgba(179,84,58,.1)", border: "#B3543A" },
            ] as const).map(d => (
              <button key={d.val} onClick={() => submitDecision(d.val)}
                style={{ padding: "10px 18px", borderRadius: 10, cursor: "pointer", fontFamily: "inherit", fontSize: 12, fontWeight: 600, color: d.color, background: decision === d.val ? d.bg : "transparent", border: `1.5px solid ${decision === d.val ? d.border : "rgba(237, 237, 234, 0.08)"}`, transition: "all .15s" }}>
                {d.label}
              </button>
            ))}
            {decision && (
              <div style={{ marginLeft: "auto", alignSelf: "center", fontSize: 12, color: "#5C9A6C", display: "flex", alignItems: "center", gap: 4 }}>
                <Check size={14} strokeWidth={3} />
                <span>Recorded</span>
              </div>
            )}
          </div>

          {/* Notify Candidate — a deliberate, separate step from recording the
              decision above. Saving a decision never auto-emails anyone. */}
          {decision && (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid rgba(237, 237, 234, 0.08)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <button
                  onClick={sendDefaultNotification}
                  disabled={notifyState === "sending"}
                  style={{
                    padding: "9px 18px", borderRadius: 9, cursor: notifyState === "sending" ? "default" : "pointer",
                    fontFamily: "inherit", fontSize: 12, fontWeight: 600,
                    color: "#0E0F13", background: notifyState === "sending" ? "#8A8B82" : "#B98A3E",
                    border: "none", opacity: notifyState === "sent" ? 0.6 : 1,
                    display: "flex", alignItems: "center", gap: 6
                  }}>
                  <Mail size={14} />
                  <span>{notifyState === "sending" ? "Sending…" : "Notify Candidate"}</span>
                </button>
                <button
                  onClick={openNotifyEditor}
                  disabled={notifyDraftLoading || notifyState === "sending"}
                  title="Edit the email before sending"
                  style={{
                    padding: "9px 12px", borderRadius: 9, cursor: "pointer", fontFamily: "inherit",
                    fontSize: 13, color: "#B98A3E", background: "transparent", border: "1.5px solid rgba(237, 237, 234, 0.08)",
                    display: "flex", alignItems: "center", justifyContent: "center"
                  }}>
                  {notifyDraftLoading ? "…" : <Edit2 size={13} />}
                </button>
                {notifyMessage && (
                  <div style={{ fontSize: 12, color: notifyState === "error" ? "#B3543A" : "#5C9A6C" }}>
                    {notifyMessage}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Edit-before-sending modal */}
      {notifyEditorOpen && notifyDraft && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(18,20,26,.7)", display: "flex",
          alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20,
        }}>
          <div style={{
            background: "#191B22", border: "1px solid rgba(237, 237, 234, 0.08)", borderRadius: 10,
            padding: 24, width: "100%", maxWidth: 560, maxHeight: "85vh", overflowY: "auto",
          }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#EDEDEA", marginBottom: 4 }}>
              Edit email before sending
            </div>
            <div style={{ fontSize: 12, color: "#8A8B82", marginBottom: 18 }}>
              To: {notifyDraft.candidate_email || "no email on file"}
            </div>

            {!notifyDraft.has_email && (
              <div style={{ padding: "10px 14px", background: "rgba(179,84,58,.1)", border: "1px solid #B3543A", borderRadius: 8, fontSize: 12, color: "#B3543A", marginBottom: 14 }}>
                No email address was found on this resume. Sending is disabled until one is added below.
              </div>
            )}

            <label style={{ fontSize: 11, color: "#8A8B82", display: "block", marginBottom: 6 }}>Candidate email</label>
            <input
              value={notifyDraft.candidate_email || ""}
              onChange={e => setNotifyDraft({ ...notifyDraft, candidate_email: e.target.value, has_email: e.target.value.trim().length > 3 })}
              placeholder="candidate@example.com"
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", borderRadius: 8, border: "1px solid rgba(237, 237, 234, 0.08)", background: "#0E0F13", color: "#EDEDEA", fontSize: 13, marginBottom: 14 }}
            />

            <label style={{ fontSize: 11, color: "#8A8B82", display: "block", marginBottom: 6 }}>Subject</label>
            <input
              value={notifyDraft.subject}
              onChange={e => setNotifyDraft({ ...notifyDraft, subject: e.target.value })}
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", borderRadius: 8, border: "1px solid rgba(237, 237, 234, 0.08)", background: "#0E0F13", color: "#EDEDEA", fontSize: 13, marginBottom: 14 }}
            />

            <label style={{ fontSize: 11, color: "#8A8B82", display: "block", marginBottom: 6 }}>Message</label>
            <textarea
              value={notifyDraft.body}
              onChange={e => setNotifyDraft({ ...notifyDraft, body: e.target.value })}
              rows={10}
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", borderRadius: 8, border: "1px solid rgba(237, 237, 234, 0.08)", background: "#0E0F13", color: "#EDEDEA", fontSize: 13, fontFamily: "inherit", lineHeight: 1.6, resize: "vertical", marginBottom: 16 }}
            />

            {notifyMessage && notifyState === "error" && (
              <div style={{ fontSize: 12, color: "#B3543A", marginBottom: 14 }}>{notifyMessage}</div>
            )}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setNotifyEditorOpen(false)}
                style={{ padding: "9px 16px", borderRadius: 8, border: "1.5px solid rgba(237, 237, 234, 0.08)", background: "transparent", color: "#8A8B82", fontSize: 12, fontFamily: "inherit", cursor: "pointer" }}>
                Cancel
              </button>
              <button
                onClick={sendEditedNotification}
                disabled={!notifyDraft.has_email || notifyState === "sending"}
                style={{
                  padding: "9px 18px", borderRadius: 8, border: "none", cursor: notifyDraft.has_email ? "pointer" : "not-allowed",
                  background: notifyDraft.has_email ? "#B98A3E" : "rgba(237, 237, 234, 0.12)", color: "#0E0F13", fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                  opacity: notifyState === "sending" ? 0.6 : 1,
                }}>
                {notifyState === "sending" ? "Sending…" : "Send Email"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
