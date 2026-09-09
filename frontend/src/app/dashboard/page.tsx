"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, authAPI, APIError } from "@/lib/api";
import type { ReportSummary } from "@/types";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";
import { color, gradient, radius } from "@/lib/design-tokens";
import { Card, Button, TextInput, StatCard, PageShell } from "@/components/ui/primitives";
import { AppNavbar } from "@/components/ui/AppNavbar";
import { SystemStatus } from "@/components/ui/SystemStatus";
import {
  Search,
  FileText,
  BarChart3,
  CheckCircle2,
  AlertTriangle,
  TrendingUp,
  Download,
  User as UserIcon,
} from "lucide-react";

function scoreColor(n: number) {
  if (n >= 75) return "#5C9A6C";
  if (n >= 55) return "#B98A3E";
  return "#B3543A";
}

function relTime(iso: string) {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "score_desc", label: "Score: High → Low" },
  { value: "score_asc", label: "Score: Low → High" },
  { value: "name_asc", label: "Name: A → Z" },
];

export default function DashboardPage() {
  const router = useRouter();
  const { user, token, logout, sessionChecked, setAuth } = useAuthStore();
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checkingOAuth, setCheckingOAuth] = useState(true);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [exporting, setExporting] = useState(false);
  const [analytics, setAnalytics] = useState<{
    total_candidates: number;
    avg_credibility_score: number;
    distribution: { recommended: number; manual_review: number; high_risk: number };
    top_skills: { skill: string; count: number }[];
    risk_categories: Record<string, number>;
  } | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic id of the most recently issued reports request — see loadReports.
  const reportsRequestRef = useRef(0);

  // Handle Supabase OAuth redirect (e.g. Google Sign In: /dashboard#access_token=...)
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.hash.includes("access_token")) {
      const hash = window.location.hash.substring(1);
      const params = new URLSearchParams(hash);
      const accessToken = params.get("access_token");
      if (accessToken) {
        authAPI.oauthVerify(accessToken)
          .then((res) => {
            setAuth(res.access_token, res.user);
            window.history.replaceState(null, "", window.location.pathname);
            setCheckingOAuth(false);
          })
          .catch(() => {
            setCheckingOAuth(false);
          });
        return;
      }
    }
    setCheckingOAuth(false);
  }, [setAuth]);

  useEffect(() => {
    if (!checkingOAuth && sessionChecked && !token) {
      router.replace("/login");
    }
  }, [checkingOAuth, sessionChecked, token, router]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearch(searchInput.trim()), 350);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchInput]);

  const loadReports = useCallback(async () => {
    if (!token) return;
    // Sequence guard. Typing in the search box fires a request per debounce
    // tick, and responses are not guaranteed to come back in order — on a
    // cold free-tier backend they routinely don't. Without this, an older
    // response can land after a newer one and repaint the list with results
    // for a query the user already changed: the box says "adam", the rows
    // are for "ada", and nothing looks broken. Only the newest request is
    // allowed to write state.
    const requestId = ++reportsRequestRef.current;
    const isCurrent = () => requestId === reportsRequestRef.current;

    setLoading(true);
    setError(null);
    try {
      const res = await reportsAPI.list(token, { search: search || undefined, sort });
      if (!isCurrent()) return;
      setReports(res.reports);
      setTotal(res.total);
    } catch (e) {
      if (!isCurrent()) return;
      if (e instanceof APIError && e.status === 401) {
        logout(); router.replace("/login");
      } else {
        // Show what the server actually said. The API returns a readable
        // `message` on every error shape (including validation failures), and
        // collapsing all of them into one generic string means a rate limit,
        // a timeout and a real outage are indistinguishable to the person who
        // has to decide whether to retry or call someone.
        setError(e instanceof APIError ? e.message : "Could not load reports.");
      }
    } finally {
      // A superseded request must not clear the spinner either — the newer
      // one is still in flight.
      if (isCurrent()) setLoading(false);
    }
  }, [token, logout, router, search, sort]);

  useEffect(() => { loadReports(); }, [loadReports]);

  useEffect(() => {
    if (!token) return;
    // Same reasoning as above, plus: don't setState after unmount if the
    // recruiter navigates away while this is in flight.
    let cancelled = false;
    reportsAPI
      .analytics(token)
      .then((a) => { if (!cancelled) setAnalytics(a); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [token]);

  const handleExportAll = async () => {
    if (!token) return;
    setExporting(true);
    try {
      const blob = await reportsAPI.downloadAllCsv(token, { search: search || undefined, sort });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "hirelens_all_reports.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("Could not export reports. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  const recommended = reports.filter(r => r.recommendation === "recommended").length;
  const highRisk    = reports.filter(r => r.recommendation === "high_risk").length;
  const avgScore    = reports.length ? Math.round(reports.reduce((s, r) => s + (r.overall_score || 0), 0) / reports.length) : 0;

  return (
    <PageShell>
      <AppNavbar />

      {/* Main Content Container */}
      <div style={{ maxWidth: 1120, margin: "0 auto", padding: "36px 24px 80px" }}>
        
        {/* Header Title */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 className="font-display" style={{ margin: 0, fontSize: 28, fontWeight: 600, color: color.textPrimary }}>Dashboard</h1>
            <p style={{ margin: "6px 0 0", fontSize: 14, color: color.textMuted }}>
              {user?.full_name ? `Welcome back, ${user.full_name}` : "Real-time candidate credibility intelligence"}
            </p>
          </div>
          
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <SystemStatus />
            <Link href="/analyze" style={{
              padding: "10px 18px", borderRadius: radius.md,
              background: color.brand,
              color: "#F5F5F2", fontWeight: 600, fontSize: 13, textDecoration: "none",
            }}>
              + Analyze Resume
            </Link>
          </div>
        </div>

        {/* 4 Hero Stats Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 14, marginBottom: 28 }}>
          <StatCard label="Total Analyzed" value={total} tone="info" icon={<FileText size={16} color={color.brand} />} />
          <StatCard label="Avg Score" value={avgScore} tone="info" icon={<BarChart3 size={16} color={color.info} />} />
          <StatCard label="Recommended" value={recommended} tone="success" icon={<CheckCircle2 size={16} color={color.success} />} />
          <StatCard label="High Risk" value={highRisk} tone="danger" icon={<AlertTriangle size={16} color={color.danger} />} />
        </div>

        {/* Enterprise Talent Intelligence Panel */}
        {analytics && analytics.top_skills && analytics.top_skills.length > 0 && (
          <Card style={{
            padding: "16px 20px", marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16
          }}>
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: color.textSecondary, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                <TrendingUp size={14} color={color.brandLight} /> Talent pool intelligence
              </div>
              <div style={{ fontSize: 13, color: color.textMuted }}>
                Top in-demand verified skills across your candidate pipeline:
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {analytics.top_skills.slice(0, 6).map(s => (
                <span key={s.skill} style={{
                  padding: "4px 10px", borderRadius: radius.sm, background: color.surfaceRaised,
                  border: `1px solid ${color.border}`, color: color.textSecondary, fontSize: 12, fontWeight: 500
                }}>
                  {s.skill} ({s.count})
                </span>
              ))}
            </div>
          </Card>
        )}

        {/* Search + Filter toolbar */}
        <div style={{ display: "flex", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 260px", position: "relative" }}>
            <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", display: "flex", alignItems: "center" }}>
              <Search size={14} color={color.textFaint} />
            </span>
            <TextInput
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by candidate name or skill…"
              style={{ paddingLeft: 40 }}
            />
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            style={{
              padding: "11px 16px", background: "rgba(30, 41, 59, 0.7)", border: `1px solid ${color.border}`,
              borderRadius: radius.md, color: color.textSecondary, fontSize: 13, cursor: "pointer", outline: "none"
            }}
          >
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value} style={{ background: "#12141A", color: color.textPrimary }}>{o.label}</option>)}
          </select>
          <Button
            variant="secondary"
            onClick={handleExportAll}
            disabled={exporting || reports.length === 0}
            style={{ whiteSpace: "nowrap" }}
          >
            <Download size={14} />
            <span>{exporting ? "Exporting…" : "Export CSV"}</span>
          </Button>
        </div>

        {/* Candidate Reports Table Container */}
        <Card style={{ overflow: "hidden" }}>
          <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(237, 237, 234, 0.08)", fontSize: 13, fontWeight: 600, color: "#B4B4AC", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{search ? `Results for "${search}"` : "Recent Candidate Intelligence Reports"}</span>
            {!loading && <span style={{ color: color.textFaint, fontWeight: 500 }}>{total} total candidate{total !== 1 ? "s" : ""}</span>}
          </div>

          {loading && (
            <div style={{ padding: 64, textAlign: "center", color: color.textMuted, fontSize: 14 }}>Loading candidate reports…</div>
          )}
          {error && (
            <div style={{ padding: 40, textAlign: "center", color: "#B3543A", fontSize: 14 }}>{error}</div>
          )}
          {!loading && !error && reports.length === 0 && search && (
            <div style={{ padding: 64, textAlign: "center" }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
                <Search size={36} color={color.textFaint} />
              </div>
              <div style={{ fontSize: 16, fontWeight: 600, color: color.textPrimary, marginBottom: 6 }}>No matches for &quot;{search}&quot;</div>
              <div style={{ fontSize: 13, color: color.textMuted }}>Try searching for a different candidate name or skill.</div>
            </div>
          )}
          {!loading && !error && reports.length === 0 && !search && (
            <div style={{ padding: 64, textAlign: "center" }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
                <FileText size={36} color={color.textFaint} />
              </div>
              <div style={{ fontSize: 16, fontWeight: 600, color: color.textPrimary, marginBottom: 6 }}>No candidate reports yet</div>
              <div style={{ fontSize: 13, color: color.textMuted, marginBottom: 24 }}>Upload your first resume to get started</div>
              <Link href="/analyze" style={{ padding: "9px 20px", borderRadius: radius.md, background: color.brand, color: "#F5F5F2", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>
                Analyze First Resume
              </Link>
            </div>
          )}

          {!loading && reports.map((r, i) => {
            const scoreCol = scoreColor(r.overall_score);
            return (
              <Link key={r.id} href={`/report/${r.id}`}
                style={{
                  display: "flex", alignItems: "center", padding: "16px 24px", gap: 16,
                  borderBottom: i < reports.length - 1 ? `1px solid ${color.borderSubtle}` : "none",
                  textDecoration: "none", transition: "all 0.15s ease", background: "transparent"
                }}
                onMouseOver={e => (e.currentTarget.style.background = color.surfaceRaised)}
                onMouseOut={e => (e.currentTarget.style.background = "transparent")}
              >
                <div style={{
                  width: 34, height: 34, borderRadius: radius.sm,
                  background: color.surfaceRaised, border: `1px solid ${color.border}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, fontWeight: 600, color: color.textSecondary, flexShrink: 0
                }}>
                  {r.candidate_name ? r.candidate_name[0].toUpperCase() : <UserIcon size={16} />}
                </div>
                
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary, marginBottom: 2 }}>{r.candidate_name || "Unknown Candidate"}</div>
                  <div style={{ fontSize: 12, color: color.textMuted, fontFamily: "var(--font-mono), monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.file_name}</div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: color.textMuted, fontWeight: 600 }}>Score</span>
                  <span style={{ fontSize: 19, fontWeight: 600, color: scoreCol, fontFamily: "var(--font-mono), monospace", minWidth: 32, textAlign: "right" }}>{r.overall_score}</span>
                </div>

                <VerdictChip verdict={verdictFromRecommendation(r.recommendation)} />

                {r.recruiter_decision && (
                  <span style={{ fontSize: 11, color: "#B4B4AC", padding: "3px 10px", border: "1px solid rgba(237, 237, 234, 0.10)", borderRadius: 6, background: "rgba(14, 15, 19, 0.4)" }}>
                    {r.recruiter_decision}
                  </span>
                )}

                <span style={{ fontSize: 12, color: color.textFaint, minWidth: 70, textAlign: "right" }}>{relTime(r.created_at)}</span>
              </Link>
            );
          })}
        </Card>
      </div>
    </PageShell>
  );
}
