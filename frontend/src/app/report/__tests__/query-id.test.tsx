import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

/**
 * The report page is one static page for every report: the id comes from
 * ?id=. These tests pin down what that page does with the query string.
 */
const getMock = vi.fn();
let search = new URLSearchParams();

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/report/",
  useSearchParams: () => search,
}));

vi.mock("@/hooks/useGoogleAuth", () => ({
  consumeOAuthFragment: () => Promise.resolve(null),
  useGoogleAuth: () => ({ signIn: vi.fn(), loading: false, error: null }),
}));

const store = {
  user: { id: "u1", email: "r@example.com", full_name: "Rec Ruiter" },
  token: "tok",
  hasHydrated: true,
  logout: vi.fn(),
  setAuth: vi.fn(),
};
vi.mock("@/store/auth", () => ({ useAuthStore: () => store }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    reportsAPI: { ...actual.reportsAPI, get: (...args: unknown[]) => getMock(...args) },
    billingAPI: {
      ...actual.billingAPI,
      usage: () => Promise.resolve({ plan: "free", limit: 0, used: 0, remaining: null, upgrade_url: null }),
    },
  };
});

import ReportPage from "../page";

const REPORT = {
  id: "3f2a9c1e-7b4d-4e8a-9c1f-0a2b3c4d5e6f",
  candidate: { name: "Priya Raghavan" },
  credibility: { overall: 74, recommendation: "manual_review", sub_scores: {} },
  skills: { all_claimed: [], verified_by_evidence: [] },
  experience: [],
  education: [],
  timeline_gaps: [],
  flags: [],
  positive_signals: [],
  interview_questions: [],
  summary: "A summary.",
  recruiter_decision: null,
};

beforeEach(() => {
  getMock.mockReset();
});

describe("report page", () => {
  it("loads the report named by ?id=", async () => {
    search = new URLSearchParams({ id: REPORT.id });
    getMock.mockResolvedValue(REPORT);
    render(<ReportPage />);
    expect(await screen.findByText("Priya Raghavan")).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith(REPORT.id, "tok");
  });

  it("says the link is incomplete when there is no id, instead of loading forever", async () => {
    search = new URLSearchParams();
    render(<ReportPage />);
    expect(await screen.findByText("This link doesn't say which report to open.")).toBeInTheDocument();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("starts fresh when the id changes, rather than showing the previous report", async () => {
    search = new URLSearchParams({ id: REPORT.id });
    getMock.mockResolvedValueOnce(REPORT);
    const view = render(<ReportPage />);
    expect(await screen.findByText("Priya Raghavan")).toBeInTheDocument();

    const other = { ...REPORT, id: "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", candidate: { name: "Omar Haddad" } };
    let resolveOther: (r: typeof other) => void = () => {};
    getMock.mockReturnValueOnce(new Promise((r) => (resolveOther = r)));
    search = new URLSearchParams({ id: other.id });
    view.rerender(<ReportPage />);

    // While the second report loads, the first one is gone.
    await waitFor(() => expect(screen.queryByText("Priya Raghavan")).not.toBeInTheDocument());
    resolveOther(other);
    expect(await screen.findByText("Omar Haddad")).toBeInTheDocument();
    expect(getMock).toHaveBeenLastCalledWith(other.id, "tok");
  });
});
