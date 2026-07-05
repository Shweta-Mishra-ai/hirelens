"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, APIError } from "@/lib/api";
import type { Report } from "@/types";

function scoreColor(n: number) {
  if (n >= 75) return "#10B981";
  if (n >= 55) return "#FBBF24";
  return "#F87171";
}

function recLabel(r: string) {
  const m: Record<string, { label: string; color: string; bg: string }> = {
    recommended:   { label: "Recommended",   color: "#10B981", bg: "rgba(5,150,105,0.1)" },
    manual_review: { label: "Manual Review", color: "#FBBF24", bg: "rgba(217,119,6,0.1)" },
    high_risk:     { label: "High Risk",     color: "#F87171", bg: "rgba(220,38,38,0.1)" },
  };
  return m[r] || m.manual_review;
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

export default function DashboardPage() {
  const router = useRouter();
  const { user, token, logout } = useAuthStore();
  const [reports, setReports] = useState<Report[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) { router.replace("/login"); return; }
  }, [token, router]);

  const loadReports = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await reportsAPI.list(token);
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
  }, [token, logout, router]);

  useEffect(() => { loadReports(); }, [loadReports]);

  // Dashboard stats
  const recommended = reports.filter(r => (r as any).recommendation === "recommended").length;
  const highRisk    = reports.filter(r => (r as any).recommendation === "high_risk").length;
  const avgScore    = reports.length ? Math.round(reports.reduce((s, r) => s + ((r as any).overall_score || 0), 0) / reports.length) : 0;

  return (
    <div style={{ minHeight: "100vh", background: "#060F1A" }}>
      {/* Navbar */}
      <nav style={{ height: 54, borderBottom: "1px solid #172840", display: "flex", alignItems: "center", paddingInline: 24, gap: 20, position: "sticky", top: 0, background: "rgba(6,15,26,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EFF6FF", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 13, color: "#64748B" }}>{user?.email}</span>
        <button onClick={() => { logout(); router.replace("/login"); }}
          style={{ padding: "5px 14px", borderRadius: 8, border: "1px solid #172840", background: "none", color: "#64748B", cursor: "pointer", fontSize: 12, fontFamily: "inherit" }}>
          Sign Out
        </button>
      </nav>

      <div style={{ maxWidth: 960, margin: "0 auto", padding: "32px 20px 80px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28, flexWrap: "wrap", gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#EFF6FF", letterSpacing: -.5 }}>Dashboard</h1>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748B" }}>
              {user?.full_name ? `Welcome back, ${user.full_name}` : "Your resume analyses"}
            </p>
          </div>
          <Link href="/analyze" style={{ padding: "10px 20px", borderRadius: 10, background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 13, textDecoration: "none" }}>
            + Analyze Resume
          </Link>
        </div>

        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 28 }}>
          {[
            { n: total,       label: "Total Analyzed", color: "#4B8DFF", icon: "📄" },
            { n: avgScore,    label: "Avg Score",       color: "#22D3EE", icon: "📊" },
            { n: recommended, label: "Recommended",    color: "#10B981", icon: "✅" },
            { n: highRisk,    label: "High Risk",      color: "#F87171", icon: "🚨" },
          ].map(s => (
            <div key={s.label} style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 14, padding: "18px 16px" }}>
              <div style={{ fontSize: 20, marginBottom: 8 }}>{s.icon}</div>
              <div style={{ fontSize: 24, fontWeight: 900, color: s.color, fontFamily: "monospace", letterSpacing: -1 }}>{s.n}</div>
              <div style={{ fontSize: 11, color: "#64748B", marginTop: 3 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Reports table */}
        <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 16, overflow: "hidden" }}>
          <div style={{ padding: "14px 22px", borderBottom: "1px solid #172840", fontSize: 12, fontWeight: 700, color: "#94A3B8" }}>
            Recent Analyses
          </div>

          {loading && (
            <div style={{ padding: 48, textAlign: "center", color: "#64748B", fontSize: 13 }}>Loading reports…</div>
          )}
          {error && (
            <div style={{ padding: 32, textAlign: "center", color: "#F87171", fontSize: 13 }}>{error}</div>
          )}
          {!loading && !error && reports.length === 0 && (
            <div style={{ padding: 56, textAlign: "center" }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>📄</div>
              <div style={{ fontSize: 15, color: "#EFF6FF", marginBottom: 8 }}>No analyses yet</div>
              <div style={{ fontSize: 13, color: "#64748B", marginBottom: 20 }}>Upload a resume to get started</div>
              <Link href="/analyze" style={{ padding: "10px 24px", borderRadius: 10, background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 13, textDecoration: "none" }}>
                Analyze First Resume
              </Link>
            </div>
          )}

          {!loading && reports.map((r: any, i) => {
            const rec = recLabel(r.recommendation);
            return (
              <Link key={r.id} href={`/report/${r.id}`}
                style={{ display: "flex", alignItems: "center", padding: "13px 22px", gap: 14, borderBottom: i < reports.length - 1 ? "1px solid #172840" : "none", textDecoration: "none", transition: "background .12s", background: "transparent" }}
                onMouseOver={e => (e.currentTarget.style.background = "#122032")}
                onMouseOut={e => (e.currentTarget.style.background = "transparent")}
              >
                <div style={{ width: 34, height: 34, borderRadius: 9, background: "rgba(29,106,255,0.12)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 }}>👤</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#EFF6FF" }}>{r.candidate_name || "Unknown"}</div>
                  <div style={{ fontSize: 11, color: "#64748B", fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.file_name}</div>
                </div>
                <div style={{ fontSize: 18, fontWeight: 800, color: scoreColor(r.overall_score), fontFamily: "monospace", minWidth: 36, textAlign: "right" }}>{r.overall_score}</div>
                <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600, color: rec.color, background: rec.bg, whiteSpace: "nowrap" }}>{rec.label}</span>
                {r.recruiter_decision && (
                  <span style={{ fontSize: 11, color: "#64748B", padding: "3px 8px", border: "1px solid #172840", borderRadius: 6 }}>{r.recruiter_decision}</span>
                )}
                <span style={{ fontSize: 11, color: "#475569", minWidth: 70, textAlign: "right" }}>{relTime(r.created_at)}</span>
                <span style={{ color: "#475569", fontSize: 12 }}>→</span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
