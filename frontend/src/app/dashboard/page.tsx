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
  Layers,
  Crosshair,
  AlertTriangle,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { reportsAPI, APIError } from "@/lib/api";
import { consumeOAuthFragment } from "@/hooks/useGoogleAuth";
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
import { cn } from "@/lib/cn";
import type { ReportSummary, PoolAnalytics } from "@/types";

const SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "score_desc", label: "Score: high to low" },
  { value: "score_asc", label: "Score: low to high" },
  { value: "name_asc", label: "Name: A to Z" },
] as const;

const FILTERS = [
  { value: "", label: "All" },
  { value: "recommended", label: "Recommended" },
  { value: "manual_review", label: "Needs review" },
  { value: "high_risk", label: "High risk" },
] as const;

/**
 * The summary strip.
 *
 * This replaces four equal-weight KPI tiles. Three of those numbers were
 * computed from the current page of results rather than the whole pool, so
 * they changed whenever you searched — and "Recommended: 3" next to
 * "High risk: 0" gave no sense of proportion. One bar carries the
 * distribution; the two numbers that actually stand alone stay as numbers.
 */
function PoolSummary({
  analytics,
  activeFilter,
  onFilter,
}: {
  analytics: PoolAnalytics | null;
  activeFilter: string;
  onFilter: (value: string) => void;
}) {
  if (!analytics) return <Skeleton className="h-[5.5rem]" />;

  const { recommended, manual_review, high_risk } = analytics.distribution;
  const total = recommended + manual_review + high_risk;
  const segments = [
    { key: "recommended", label: "Recommended", n: recommended, color: "#3DD68C" },
    { key: "manual_review", label: "Needs review", n: manual_review, color: "#E8B341" },
    { key: "high_risk", label: "High risk", n: high_risk, color: "#F2555A" },
  ];

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-x-10 gap-y-5">
        <div>
          <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
            Candidates analysed
          </div>
          <div className="mt-1 text-3xl font-semibold tabular leading-none text-content">
            {analytics.total_candidates}
          </div>
        </div>

        <div>
          <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
            Average credibility
          </div>
          <div
            className="mt-1 text-3xl font-semibold tabular leading-none"
            style={{
              color: analytics.total_candidates
                ? scoreColor(analytics.avg_credibility_score)
                : undefined,
            }}
          >
            {analytics.total_candidates ? analytics.avg_credibility_score : "—"}
          </div>
        </div>

        {total > 0 && (
          <div className="min-w-[16rem] flex-1">
            <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
              Distribution
            </div>
            <div
              className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-canvas-inset"
              role="img"
              aria-label={segments.map((s) => `${s.label}: ${s.n}`).join(", ")}
            >
              {segments
                .filter((s) => s.n > 0)
                .map((s) => (
                  <div
                    key={s.key}
                    style={{ width: `${(s.n / total) * 100}%`, background: s.color }}
                  />
                ))}
            </div>
            {/* Doubles as a filter — the segments are the categories you'd
                want to narrow to anyway. */}
            <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
              {segments.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => onFilter(activeFilter === s.key ? "" : s.key)}
                  aria-pressed={activeFilter === s.key}
                  className={cn(
                    "flex items-center gap-1.5 rounded text-xs transition-colors",
                    "focus-visible:outline-none focus-visible:shadow-focus",
                    activeFilter === s.key
                      ? "text-content"
                      : "text-content-muted hover:text-content",
                  )}
                >
                  <span aria-hidden className="size-1.5 rounded-full" style={{ background: s.color }} />
                  {s.label}
                  <span className="tabular text-content-faint">{s.n}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
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

/** Shown only when the recruiter has nothing yet — the three ways to start. */
function GettingStarted() {
  const paths = [
    { href: "/analyze", icon: ScanLine, title: "Analyze one resume", body: "Upload a single PDF or DOCX and get a full credibility report." },
    { href: "/bulk", icon: Layers, title: "Screen a batch", body: "Upload up to 50 at once and rank them by credibility." },
    { href: "/match", icon: Crosshair, title: "Match against a role", body: "Paste a job description and see who actually fits it." },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {paths.map(({ href, icon: Icon, title, body }) => (
        <Link key={href} href={href} className="focus-visible:outline-none">
          <Card interactive className="h-full p-4">
            <Icon aria-hidden className="size-4 text-brand-400" />
            <h3 className="mt-3 text-sm font-medium text-content">{title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-content-faint">{body}</p>
          </Card>
        </Link>
      ))}
    </div>
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
  const [recommendation, setRecommendation] = useState("");
  const [exporting, setExporting] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Complete the Google OAuth round trip. Supabase redirects back here with
  // the token in the URL fragment; it is exchanged for a HireLens session and
  // stripped from the address bar so a refresh can't replay it.
  const [checkingOAuth, setCheckingOAuth] = useState(true);
  useEffect(() => {
    let cancelled = false;
    consumeOAuthFragment()
      .then((result) => {
        if (cancelled || !result) return;
        if (result.ok) {
          setAuth(result.token, result.user as never);
        } else {
          setError(result.error);
        }
      })
      .finally(() => {
        if (!cancelled) setCheckingOAuth(false);
      });
    return () => {
      cancelled = true;
    };
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
      const res = await reportsAPI.list(token, {
        search: search || undefined,
        sort,
        recommendation: recommendation || undefined,
      });
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
  }, [token, logout, router, search, sort, recommendation]);

  useEffect(() => {
    if (!checkingOAuth) void loadReports();
  }, [loadReports, checkingOAuth]);

  useEffect(() => {
    if (!token || checkingOAuth) return;
    reportsAPI.analytics(token).then(setAnalytics).catch(() => {
      // Analytics is supplementary — a failure must not blank the page.
    });
  }, [token, checkingOAuth]);

  async function handleExport() {
    if (!token) return;
    setExporting(true);
    try {
      const blob = await reportsAPI.downloadAllCsv(token, {
        search: search || undefined,
        sort,
        recommendation: recommendation || undefined,
      });
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

  const needsAttention = useMemo(
    () =>
      analytics
        ? analytics.distribution.manual_review + analytics.distribution.high_risk
        : 0,
    [analytics],
  );

  const firstName = user?.full_name?.split(" ")[0];
  const isEmptyWorkspace = !loading && total === 0 && !search && !recommendation;

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
        <Alert tone="error" className="mb-5" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {isEmptyWorkspace ? (
        <div className="space-y-6">
          <Card>
            <EmptyState
              icon={<FileText className="size-5" />}
              title="No candidate files yet"
              description="Upload a resume and HireLens returns a credibility assessment with every claim traced back to the text that produced it."
            />
          </Card>
          <GettingStarted />
        </div>
      ) : (
        <div className="space-y-5">
          <PoolSummary
            analytics={analytics}
            activeFilter={recommendation}
            onFilter={setRecommendation}
          />

          {needsAttention > 0 && (
            <button
              type="button"
              onClick={() => setRecommendation(recommendation ? "" : "manual_review")}
              className="flex w-full items-center gap-2.5 rounded-lg border border-caution-line bg-caution-soft px-3.5 py-2.5 text-left text-sm text-caution transition-colors hover:bg-caution/[0.16] focus-visible:outline-none focus-visible:shadow-focus"
            >
              <AlertTriangle aria-hidden className="size-4 shrink-0" />
              <span className="flex-1">
                {pluralize(needsAttention, "candidate")} flagged for a closer look.
              </span>
              <span className="text-xs text-content-muted">
                {recommendation ? "Show all" : "Review them"}
              </span>
            </button>
          )}

          <div className="flex flex-wrap items-end gap-3">
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
            <div className="w-44">
              <Select
                value={recommendation}
                onChange={(e) => setRecommendation(e.target.value)}
                options={FILTERS}
                aria-label="Filter by verdict"
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
              <EmptyState
                icon={<SearchX className="size-5" />}
                title="Nothing matches those filters"
                description="Try a different search term, or clear the verdict filter."
                action={
                  <Button
                    onClick={() => {
                      setSearchInput("");
                      setRecommendation("");
                    }}
                  >
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <div className="divide-y divide-line-subtle">
                {reports.map((r) => (
                  <ReportRow key={r.id} report={r} />
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
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
