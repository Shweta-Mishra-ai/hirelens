"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, authAPI, APIError } from "@/lib/api";
import type { Report } from "@/types";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";

function scoreColor(n: number) {
  if (n >= 75) return "#10B981";
  if (n >= 55) return "#F59E0B";
  return "#EF4444";
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
  const pathname = usePathname();
  const { user, token, logout, hasHydrated, setAuth } = useAuthStore();
  const [reports, setReports] = useState<Report[]>([]);
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
    if (!checkingOAuth && hasHydrated && !token) {
      router.replace("/login");
    }
  }, [checkingOAuth, hasHydrated, token, router]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearch(searchInput.trim()), 350);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchInput]);

  const loadReports = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await reportsAPI.list(token, { search: search || undefined, sort });
      setReports(res.reports as unknown as Report[]);
      setTotal(res.total);
    } catch (e) {
      if (e instanceof APIError && e.status === 401) {
        logout(); router.replace("/login");
      } else {
        setError("Could not load reports.");
      }
    } finally {
      setLoading(false);
    }
  }, [token, logout, router, search, sort]);

  useEffect(() => { loadReports(); }, [loadReports]);

  useEffect(() => {
    if (!token) return;
    reportsAPI.analytics(token).then(setAnalytics).catch(() => {});
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

  const recommended = reports.filter(r => (r as any).recommendation === "recommended").length;
  const highRisk    = reports.filter(r => (r as any).recommendation === "high_risk").length;
  const avgScore    = reports.length ? Math.round(reports.reduce((s, r) => s + ((r as any).overall_score || 0), 0) / reports.length) : 0;

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

        {/* User profile & logout */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", borderRadius: 99, background: "rgba(30,41,59,0.6)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ width: 22, height: 22, borderRadius: "50%", background: "#6366F1", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>
              {user?.full_name ? user.full_name[0].toUpperCase() : "U"}
            </div>
            <span style={{ fontSize: 12, color: "#CBD5E1", fontWeight: 500 }}>{user?.email}</span>
          </div>
          <button onClick={() => { logout(); router.replace("/login"); }}
            style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(30,41,59,0.4)", color: "#94A3B8", cursor: "pointer", fontSize: 12, fontWeight: 600, transition: "all 0.15s" }}>
            Sign Out
          </button>
        </div>
      </nav>

      {/* Main Content Container */}
      <div style={{ maxWidth: 1120, margin: "0 auto", padding: "36px 24px 80px" }}>
        
        {/* Header Title */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 30, fontWeight: 800, color: "#F8FAFC", letterSpacing: -0.7 }}>Dashboard</h1>
            <p style={{ margin: "6px 0 0", fontSize: 14, color: "#94A3B8" }}>
              {user?.full_name ? `Welcome back, ${user.full_name}` : "Real-time candidate credibility intelligence"}
            </p>
          </div>
          
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ padding: "6px 12px", borderRadius: 99, background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.3)", color: "#10B981", fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#10B981", boxShadow: "0 0 8px #10B981" }} />
              5,000 Capacity Active
            </span>
            <Link href="/analyze" style={{
              padding: "10px 20px", borderRadius: 10,
              background: "linear-gradient(135deg, #6366F1, #4F46E5)",
              color: "#FFFFFF", fontWeight: 700, fontSize: 13, textDecoration: "none",
              boxShadow: "0 4px 16px rgba(99,102,241,0.35)", transition: "transform 0.15s ease"
            }}>
              + Analyze Resume
            </Link>
          </div>
        </div>

        {/* 4 Hero Stats Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 16, marginBottom: 28 }}>
          {[
            { n: total, label: "Total Analyzed", color: "#6366F1", icon: "📄", bg: "rgba(99,102,241,0.1)", border: "rgba(99,102,241,0.25)" },
            { n: avgScore, label: "Avg Score", color: "#3B82F6", icon: "📊", bg: "rgba(59,130,246,0.1)", border: "rgba(59,130,246,0.25)" },
            { n: recommended, label: "Recommended", color: "#10B981", icon: "✅", bg: "rgba(16,185,129,0.1)", border: "rgba(16,185,129,0.25)" },
            { n: highRisk, label: "High Risk", color: "#EF4444", icon: "🚨", bg: "rgba(239,68,68,0.1)", border: "rgba(239,68,68,0.25)" },
          ].map(s => (
            <div key={s.label} style={{
              background: "rgba(30, 41, 59, 0.6)",
              backdropFilter: "blur(12px)",
              border: `1px solid ${s.border}`,
              borderRadius: 16, padding: "20px 20px",
              display: "flex", flexDirection: "column", gap: 8
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#94A3B8", textTransform: "uppercase", letterSpacing: 0.5 }}>{s.label}</span>
                <div style={{ width: 34, height: 34, borderRadius: 10, background: s.bg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>{s.icon}</div>
              </div>
              <div style={{ fontSize: 32, fontWeight: 900, color: s.color, fontFamily: "var(--font-mono), monospace", letterSpacing: -1 }}>{s.n}</div>
            </div>
          ))}
        </div>

        {/* Enterprise Talent Intelligence Panel */}
        {analytics && analytics.top_skills && analytics.top_skills.length > 0 && (
          <div style={{
            background: "rgba(30, 41, 59, 0.5)", backdropFilter: "blur(12px)",
            border: "1px solid rgba(99, 102, 241, 0.2)", borderRadius: 16,
            padding: "18px 22px", marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16
          }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#818CF8", letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 4 }}>
                📈 Enterprise Talent Pool Intelligence
              </div>
              <div style={{ fontSize: 13, color: "#CBD5E1" }}>
                Top in-demand verified skills across your candidate pipeline:
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {analytics.top_skills.slice(0, 6).map(s => (
                <span key={s.skill} style={{
                  padding: "4px 10px", borderRadius: 8, background: "rgba(99, 102, 241, 0.15)",
                  border: "1px solid rgba(99, 102, 241, 0.3)", color: "#C7D2FE", fontSize: 12, fontWeight: 600
                }}>
                  {s.skill} ({s.count})
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Search + Filter toolbar */}
        <div style={{ display: "flex", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 260px", position: "relative" }}>
            <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", fontSize: 14, color: "#64748B" }}>🔍</span>
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by candidate name or skill…"
              style={{
                width: "100%", boxSizing: "border-box", padding: "11px 14px 11px 40px",
                background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: 12, color: "#F8FAFC", fontSize: 13, outline: "none",
              }}
            />
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            style={{
              padding: "11px 16px", background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: 12, color: "#CBD5E1", fontSize: 13, cursor: "pointer", outline: "none"
            }}
          >
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value} style={{ background: "#0F172A", color: "#F8FAFC" }}>{o.label}</option>)}
          </select>
          <button
            onClick={handleExportAll}
            disabled={exporting || reports.length === 0}
            style={{
              padding: "11px 20px", borderRadius: 12, border: "1px solid rgba(255, 255, 255, 0.1)",
              background: "rgba(30, 41, 59, 0.7)", color: "#CBD5E1", fontWeight: 700, fontSize: 13,
              cursor: exporting || reports.length === 0 ? "default" : "pointer",
              opacity: exporting || reports.length === 0 ? 0.5 : 1, whiteSpace: "nowrap",
            }}
          >
            {exporting ? "Exporting…" : "⬇ Export All CSV"}
          </button>
        </div>

        {/* Candidate Reports Table Container */}
        <div style={{
          background: "rgba(30, 41, 59, 0.6)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: 20, overflow: "hidden"
        }}>
          <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255, 255, 255, 0.08)", fontSize: 13, fontWeight: 700, color: "#CBD5E1", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{search ? `Results for "${search}"` : "Recent Candidate Intelligence Reports"}</span>
            {!loading && <span style={{ color: "#64748B", fontWeight: 500 }}>{total} total candidate{total !== 1 ? "s" : ""}</span>}
          </div>

          {loading && (
            <div style={{ padding: 64, textAlign: "center", color: "#94A3B8", fontSize: 14 }}>Loading candidate reports…</div>
          )}
          {error && (
            <div style={{ padding: 40, textAlign: "center", color: "#EF4444", fontSize: 14 }}>{error}</div>
          )}
          {!loading && !error && reports.length === 0 && search && (
            <div style={{ padding: 64, textAlign: "center" }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "#F8FAFC", marginBottom: 6 }}>No matches for &quot;{search}&quot;</div>
              <div style={{ fontSize: 13, color: "#94A3B8" }}>Try searching for a different candidate name or skill.</div>
            </div>
          )}
          {!loading && !error && reports.length === 0 && !search && (
            <div style={{ padding: 64, textAlign: "center" }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>📄</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "#F8FAFC", marginBottom: 6 }}>No candidate reports yet</div>
              <div style={{ fontSize: 13, color: "#94A3B8", marginBottom: 24 }}>Upload your first resume to get started</div>
              <Link href="/analyze" style={{ padding: "10px 24px", borderRadius: 10, background: "linear-gradient(135deg, #6366F1, #4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 13, textDecoration: "none" }}>
                Analyze First Resume
              </Link>
            </div>
          )}

          {!loading && reports.map((r: any, i) => {
            const color = scoreColor(r.overall_score);
            return (
              <Link key={r.id} href={`/report/${r.id}`}
                style={{
                  display: "flex", alignItems: "center", padding: "16px 24px", gap: 16,
                  borderBottom: i < reports.length - 1 ? "1px solid rgba(255, 255, 255, 0.05)" : "none",
                  textDecoration: "none", transition: "all 0.15s ease", background: "transparent"
                }}
                onMouseOver={e => (e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)")}
                onMouseOut={e => (e.currentTarget.style.background = "transparent")}
              >
                <div style={{
                  width: 38, height: 38, borderRadius: 12,
                  background: "rgba(99, 102, 241, 0.15)", border: "1px solid rgba(99, 102, 241, 0.3)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 14, fontWeight: 700, color: "#818CF8", flexShrink: 0
                }}>
                  {r.candidate_name ? r.candidate_name[0].toUpperCase() : "👤"}
                </div>
                
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC", marginBottom: 2 }}>{r.candidate_name || "Unknown Candidate"}</div>
                  <div style={{ fontSize: 12, color: "#94A3B8", fontFamily: "var(--font-mono), monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.file_name}</div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: "#94A3B8", fontWeight: 600 }}>Score</span>
                  <span style={{ fontSize: 20, fontWeight: 900, color, fontFamily: "var(--font-mono), monospace", minWidth: 36, textAlign: "right" }}>{r.overall_score}</span>
                </div>

                <VerdictChip verdict={verdictFromRecommendation(r.recommendation)} />

                {r.recruiter_decision && (
                  <span style={{ fontSize: 11, color: "#CBD5E1", padding: "3px 10px", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, background: "rgba(15,23,42,0.4)" }}>
                    {r.recruiter_decision}
                  </span>
                )}

                <span style={{ fontSize: 12, color: "#64748B", minWidth: 70, textAlign: "right" }}>{relTime(r.created_at)}</span>
                <span style={{ color: "#64748B", fontSize: 14 }}>→</span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
