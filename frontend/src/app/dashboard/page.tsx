"use client";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Search,
  FileText,
  Download,
  ScanLine,
  SearchX,
  ArrowRight,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, authAPI, APIError } from "@/lib/api";
import { VerdictChip, verdictFromRecommendation } from "@/components/VerdictStamp";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input, Select } from "@/components/ui/Field";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Feedback";
import { ScorePill } from "@/components/ui/Score";
import { relativeTime, absoluteTime, initials, pluralize } from "@/lib/format";
import { scoreColor } from "@/lib/design-tokens";
import type { ReportSummary, PoolAnalytics } from "@/types";

const SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "score_desc", label: "Score: high to low" },
  { value: "score_asc", label: "Score: low to high" },
  { value: "name_asc", label: "Name: A to Z" },
] as const;

/** A single headline number. Kept visually quiet so the table stays the focus. */
function Stat({
  label,
  value,
  sublabel,
  accent,
}: {
  label: string;
  value: string | number;
  sublabel?: string;
  accent?: string;
}) {
  return (
    <Card className="p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">{label}</div>
      <div
        className="mt-2 text-3xl font-semibold tabular leading-none"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
      {sublabel && <div className="mt-1.5 text-xs text-content-faint">{sublabel}</div>}
    </Card>
  );
}

/**
 * Distribution of the whole pool as a single stacked bar. This replaces two of
 * the four KPI tiles: "Recommended: 3" and "High risk: 0" as separate numbers
 * gave no sense of proportion, and both were computed from the current page of
 * results rather than the full pool, so they changed when you searched.
 */
function DistributionBar({ analytics }: { analytics: PoolAnalytics }) {
  const { recommended, manual_review, high_risk } = analytics.distribution;
  const total = recommended + manual_review + high_risk;
  if (total === 0) return null;

  const segments = [
    { key: "recommended", label: "Recommended", n: recommended, color: "#3DD68C" },
    { key: "manual_review", label: "Needs review", n: manual_review, color: "#E8B341" },
    { key: "high_risk", label: "High risk", n: high_risk, color: "#F2555A" },
  ].filter((s) => s.n > 0);

  return (
    <Card className="p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
        Pool distribution
      </div>
      <div
        className="mt-3 flex h-2 overflow-hidden rounded-full bg-canvas-inset"
        role="img"
        aria-label={segments.map((s) => `${s.label}: ${s.n}`).join(", ")}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            style={{ width: `${(s.n / total) * 100}%`, background: s.color }}
            className="h-full"
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5 text-xs text-content-muted">
            <span aria-hidden className="size-1.5 rounded-full" style={{ background: s.color }} />
            {s.label}
            <span className="tabular text-content-faint">{s.n}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ReportRow({ report }: { report: ReportSummary }) {
  return (
    <Link
      href={`/report/${report.id}`}
      className="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 px-5 py-3.5 transition-colors hover:bg-canvas-overlay/50 focus-visible:bg-canvas-overlay focus-visible:outline-none sm:grid-cols-[auto_minmax(0,1fr)_auto_auto_auto_auto]"
    >
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas-overlay text-xs font-semibold text-content-muted"
      >
        {initials(report.candidate_name)}
      </span>

      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-content">
          {report.candidate_name || "Unknown candidate"}
        </span>
        <span className="block truncate font-mono text-xs text-content-faint">
          {report.file_name || "—"}
        </span>
      </span>

      <ScorePill score={report.overall_score} />

      <span className="hidden sm:block">
        <VerdictChip verdict={verdictFromRecommendation(report.recommendation)} />
      </span>

      <span className="hidden sm:block">
        {report.recruiter_decision ? (
          <Badge tone="neutral" className="capitalize">
            {String(report.recruiter_decision).replace(/_/g, " ")}
          </Badge>
        ) : null}
      </span>

      <span className="hidden items-center gap-3 sm:flex">
        <time
          className="w-20 text-right text-xs text-content-faint"
          dateTime={report.created_at || undefined}
          title={absoluteTime(report.created_at)}
        >
          {relativeTime(report.created_at)}
        </time>
        <ArrowRight
          aria-hidden
          className="size-4 text-content-faint transition-transform group-hover:translate-x-0.5"
        />
      </span>
    </Link>
  );
}

function DashboardContent() {
  const router = useRouter();
  const { user, token, logout, setAuth } = useAuthStore();

  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analytics, setAnalytics] = useState<PoolAnalytics | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<string>("newest");
  const [exporting, setExporting] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Supabase OAuth lands back here as /dashboard#access_token=… — exchange it
  // for our own session token, then strip it from the URL so a refresh or a
  // copied link doesn't carry a credential in the fragment.
  const [checkingOAuth, setCheckingOAuth] = useState(true);
  useEffect(() => {
    if (typeof window === "undefined" || !window.location.hash.includes("access_token")) {
      setCheckingOAuth(false);
      return;
    }
    const accessToken = new URLSearchParams(window.location.hash.slice(1)).get("access_token");
    if (!accessToken) {
      setCheckingOAuth(false);
      return;
    }
    authAPI
      .oauthVerify(accessToken)
      .then((res) => {
        setAuth(res.access_token, res.user);
        window.history.replaceState(null, "", window.location.pathname);
      })
      .catch(() => {
        setError("Google sign-in could not be completed. Sign in with your email instead.");
      })
      .finally(() => setCheckingOAuth(false));
  }, [setAuth]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchInput]);

  const loadReports = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await reportsAPI.list(token, { search: search || undefined, sort });
      setReports(res.reports);
      setTotal(res.total);
    } catch (e) {
      if (e instanceof APIError && e.status === 401) {
        logout();
        router.replace("/login");
        return;
      }
      setError(e instanceof APIError ? e.message : "Could not load your reports.");
    } finally {
      setLoading(false);
    }
  }, [token, logout, router, search, sort]);

  useEffect(() => {
    if (!checkingOAuth) void loadReports();
  }, [loadReports, checkingOAuth]);

  useEffect(() => {
    if (!token || checkingOAuth) return;
    reportsAPI.analytics(token).then(setAnalytics).catch(() => {
      // Analytics is supplementary — a failure here must not blank the page.
    });
  }, [token, checkingOAuth]);

  async function handleExport() {
    if (!token) return;
    setExporting(true);
    try {
      const blob = await reportsAPI.downloadAllCsv(token, { search: search || undefined, sort });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `hirelens-reports-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not export. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  // Averages come from the analytics endpoint (whole pool) rather than the
  // current page of rows, so they stay stable while you search and sort.
  const avgScore = analytics?.avg_credibility_score ?? 0;
  const poolTotal = analytics?.total_candidates ?? total;

  const needsAttention = useMemo(
    () =>
      analytics
        ? analytics.distribution.manual_review + analytics.distribution.high_risk
        : 0,
    [analytics],
  );

  const firstName = user?.full_name?.split(" ")[0];

  return (
    <AppShell>
      <PageHeader
        title={firstName ? `Welcome back, ${firstName}` : "Dashboard"}
        description="Every candidate file you've analysed, with the evidence behind each score."
        actions={
          <Link href="/analyze">
            <Button variant="primary" icon={<ScanLine className="size-4" />}>
              Analyze resume
            </Button>
          </Link>
        }
      />

      {error && (
        <Alert tone="error" className="mb-6" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Candidates analysed" value={poolTotal} />
        <Stat
          label="Average credibility"
          value={poolTotal ? avgScore : "—"}
          accent={poolTotal ? scoreColor(avgScore) : undefined}
          sublabel={poolTotal ? "Across your whole pool" : "No data yet"}
        />
        <Stat
          label="Awaiting your review"
          value={needsAttention}
          sublabel={needsAttention ? "Flagged for a closer look" : "Nothing outstanding"}
        />
        {analytics ? (
          <DistributionBar analytics={analytics} />
        ) : (
          <Skeleton className="h-[7.5rem]" />
        )}
      </div>

      {analytics && analytics.top_skills.length > 0 && (
        <Card className="mb-6 p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
            Most common evidenced skills
          </div>
          <p className="mt-1 text-xs text-content-faint">
            Counted only where the skill appears in a role or project description, not
            merely in a skills list.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {analytics.top_skills.slice(0, 10).map((s) => (
              <Badge key={s.skill} tone="neutral">
                {s.skill}
                <span className="tabular text-content-faint">{s.count}</span>
              </Badge>
            ))}
          </div>
        </Card>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1">
          <Input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search candidates, filenames or skills…"
            icon={<Search className="size-4" />}
            aria-label="Search reports"
          />
        </div>
        <div className="w-48">
          <Select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            options={SORT_OPTIONS}
            aria-label="Sort reports"
          />
        </div>
        <Button
          onClick={handleExport}
          loading={exporting}
          disabled={reports.length === 0}
          icon={<Download className="size-4" />}
        >
          Export CSV
        </Button>
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title={search ? `Results for “${search}”` : "Candidate files"}
          action={
            !loading && (
              <span className="text-xs text-content-faint">{pluralize(total, "report")}</span>
            )
          }
        />

        {loading ? (
          <div className="divide-y divide-line-subtle">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-4 px-5 py-3.5">
                <Skeleton className="size-9 rounded-lg" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3.5 w-40" />
                  <Skeleton className="h-3 w-56" />
                </div>
                <Skeleton className="h-6 w-12" />
              </div>
            ))}
          </div>
        ) : reports.length === 0 ? (
          search ? (
            <EmptyState
              icon={<SearchX className="size-5" />}
              title={`No candidates match “${search}”`}
              description="Try a different name, filename or skill."
              action={<Button onClick={() => setSearchInput("")}>Clear search</Button>}
            />
          ) : (
            <EmptyState
              icon={<FileText className="size-5" />}
              title="No candidate files yet"
              description="Upload a resume and HireLens will return a credibility assessment with every claim traced back to the text that produced it."
              action={
                <Link href="/analyze">
                  <Button variant="primary" icon={<ScanLine className="size-4" />}>
                    Analyze your first resume
                  </Button>
                </Link>
              }
            />
          )
        ) : (
          <div className="divide-y divide-line-subtle">
            {reports.map((r) => (
              <ReportRow key={r.id} report={r} />
            ))}
          </div>
        )}
      </Card>
    </AppShell>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardContent />
    </RequireAuth>
  );
}
