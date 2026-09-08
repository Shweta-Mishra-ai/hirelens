/**
 * Page-level integration test: the dashboard.
 *
 * This is the page every logged-in recruiter lands on, and the one that
 * carried the `Report` typing bug found in an earlier pass — the report list
 * was typed against the browser's global `Report` DOM type instead of the
 * app's, so field-name mismatches between the API and the UI compiled fine
 * and rendered `undefined`. A unit test on the API client cannot catch that
 * class of bug; only rendering the page against a realistic payload can.
 *
 * So these assert on the *values a recruiter actually reads* — the candidate
 * name, the score, the verdict — not just that something rendered.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
// One stable router object. Returning a fresh `{...}` per call (the obvious
// way to write this) makes `router` a new identity on every render, which
// re-fires every useCallback/useEffect that depends on it — the test then
// measures a loop the mock created rather than the page's real behaviour.
const router = { replace, push: vi.fn(), prefetch: vi.fn(), back: vi.fn(), refresh: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/dashboard",
}));

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { signInWithOAuth: vi.fn(), signOut: vi.fn(), getSession: vi.fn() } },
}));

const listReports = vi.fn();
const analytics = vi.fn();
const healthCheck = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    reportsAPI: {
      ...actual.reportsAPI,
      list: (...a: unknown[]) => listReports(...a),
      analytics: (...a: unknown[]) => analytics(...a),
    },
    healthAPI: { check: () => healthCheck(), diagnostics: vi.fn() },
    authAPI: {
      login: vi.fn(),
      signup: vi.fn(),
      // Resolve rather than reject: the store's rehydrate callback fires
      // restoreSession() asynchronously at import time, and a rejection would
      // race each test's setState and null the token out from under it.
      session: vi.fn().mockResolvedValue({
        access_token: "tok",
        user: { id: "u1", email: "recruiter@example.com", full_name: "Recruiter" },
      }),
      me: vi.fn(),
      logout: vi.fn(),
      oauthVerify: vi.fn(),
    },
  };
});

import DashboardPage from "@/app/dashboard/page";
import { useAuthStore } from "@/store/auth";
import { APIError } from "@/lib/api";

const HEALTHY = {
  status: "ok",
  version: "1.0.0",
  env: "production",
  llm_ready: true,
  storage_mode: "supabase",
  storage_warning: null,
  config_warnings: [],
  services: {},
};

const REPORT_ROW = {
  id: "rep-1",
  file_name: "ada_lovelace_cv.pdf",
  candidate_name: "Ada Lovelace",
  overall_score: 88,
  recommendation: "recommended",
  created_at: new Date().toISOString(),
  recruiter_decision: null,
};

describe("dashboard page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    useAuthStore.setState({
      user: { id: "u1", email: "recruiter@example.com", full_name: "Recruiter" },
      token: "tok",
      sessionChecked: true,
      hasHydrated: true,
      isLoading: false,
      error: null,
    });
    healthCheck.mockResolvedValue(HEALTHY);
    analytics.mockResolvedValue({
      total_candidates: 1,
      avg_credibility_score: 88,
      distribution: { recommended: 1, manual_review: 0, high_risk: 0 },
      top_skills: [],
      risk_categories: {},
    });
  });

  it("renders a candidate row with the name and score the API returned", async () => {
    listReports.mockResolvedValue({ reports: [REPORT_ROW], total: 1, pages: 1 });

    render(<DashboardPage />);

    // The exact values — a field-name mismatch would render "undefined" here
    // and still pass a looser "something rendered" assertion.
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    // 88 appears twice — once in the Avg Score stat card, once on the row —
    // which is itself the correct behaviour worth pinning.
    await waitFor(() => expect(screen.getAllByText("88").length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  it("shows the empty state, not an error, when there are no reports yet", async () => {
    listReports.mockResolvedValue({ reports: [], total: 0, pages: 0 });

    render(<DashboardPage />);

    expect(await screen.findByText(/no candidate reports yet/i)).toBeInTheDocument();
  });

  it("surfaces an error instead of an empty list when the reports call fails", async () => {
    listReports.mockRejectedValue(new APIError(500, "internal_error", "Something broke."));

    render(<DashboardPage />);

    // An API failure rendering as "no reports" would tell a recruiter their
    // data is gone. It has to read as an error.
    await waitFor(() => expect(screen.queryByText(/no candidate reports yet/i)).not.toBeInTheDocument());
    expect(await screen.findByText("Something broke.")).toBeInTheDocument();
  });

  it("redirects to /login once the session check settles with no token", async () => {
    useAuthStore.setState({ token: null, sessionChecked: true });
    listReports.mockResolvedValue({ reports: [], total: 0, pages: 0 });

    render(<DashboardPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
