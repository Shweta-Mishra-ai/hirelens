import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReportSummary } from "@/types";

const listMock = vi.fn();
const analyticsMock = vi.fn();

// Next's router and the zustand store both hand back stable references in the
// app. Fresh objects here would change the load callback's identity on every
// render and fire duplicate requests the real page never makes.
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/dashboard",
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
    reportsAPI: {
      list: (...args: unknown[]) => listMock(...args),
      analytics: (...args: unknown[]) => analyticsMock(...args),
      downloadAllCsv: vi.fn(),
    },
  };
});

import DashboardPage from "../page";

function makeReports(prefix: string, count: number): ReportSummary[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `${prefix}-${i}`,
    candidate_name: `${prefix} Candidate ${i}`,
    file_name: `${prefix}-${i}.pdf`,
    overall_score: 70,
    recommendation: "hire",
    created_at: "2026-01-01T00:00:00+00:00",
  })) as ReportSummary[];
}

/** The page argument the API was called with on the Nth call. */
function pageArg(call: number): number | undefined {
  const params = listMock.mock.calls[call]?.[1] as { page?: number } | undefined;
  return params?.page;
}

describe("dashboard pagination", () => {
  beforeEach(() => {
    listMock.mockReset();
    analyticsMock.mockReset();
    analyticsMock.mockResolvedValue({
      total_candidates: 45,
      avg_credibility_score: 71,
      distribution: { recommended: 20, manual_review: 15, high_risk: 10 },
      top_skills: [],
      risk_categories: {},
    });
    listMock.mockResolvedValue({ reports: makeReports("p", 20), total: 45, page: 1, pages: 3 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("asks for page 1 on first load", async () => {
    render(<DashboardPage />);
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(pageArg(0)).toBe(1);
  });

  it("shows a pager only when there is more than one page", async () => {
    render(<DashboardPage />);
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();

    listMock.mockReset();
    listMock.mockResolvedValue({ reports: makeReports("p", 4), total: 4, page: 1, pages: 1 });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/sort/i), "oldest");
    await waitFor(() => expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument());
  });

  it("walks forward and back through pages", async () => {
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findByText("Page 1 of 3");
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();

    listMock.mockResolvedValue({ reports: makeReports("q", 20), total: 45, page: 2, pages: 3 });
    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3")).toBeInTheDocument());
    expect(pageArg(listMock.mock.calls.length - 1)).toBe(2);
    expect(screen.getByRole("button", { name: /previous/i })).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: /previous/i }));
    await waitFor(() => expect(pageArg(listMock.mock.calls.length - 1)).toBe(1));
  });

  it("returns to page 1 when a filter changes, in a single request", async () => {
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findByText("Page 1 of 3");

    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(pageArg(listMock.mock.calls.length - 1)).toBe(2));

    const before = listMock.mock.calls.length;
    await user.selectOptions(screen.getByLabelText(/verdict|filter|recommendation/i), "manual_review");

    // Exactly one new request, and it asks for page 1 — not one for the stale
    // page followed by a correcting one.
    await waitFor(() => expect(listMock.mock.calls.length).toBe(before + 1));
    expect(pageArg(before)).toBe(1);
  });

  it("returns to page 1 when the search box changes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<DashboardPage />);
    await screen.findByText("Page 1 of 3");

    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(pageArg(listMock.mock.calls.length - 1)).toBe(2));

    const before = listMock.mock.calls.length;
    await user.type(screen.getByPlaceholderText(/search/i), "anita");
    await act(async () => {
      vi.advanceTimersByTime(400);
    });

    await waitFor(() => expect(listMock.mock.calls.length).toBe(before + 1));
    expect(pageArg(before)).toBe(1);
    expect((listMock.mock.calls[before][1] as { search?: string }).search).toBe("anita");
  });

  it("ignores a slow response that a newer query has already replaced", async () => {
    const user = userEvent.setup();
    render(<DashboardPage />);
    await screen.findByText("Page 1 of 3");

    let releaseStale: (() => void) | undefined;
    listMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseStale = () =>
            resolve({ reports: makeReports("stale", 20), total: 45, page: 2, pages: 3 });
        }),
    );
    await user.click(screen.getByRole("button", { name: /next/i }));

    // A newer query answers first.
    listMock.mockResolvedValue({ reports: makeReports("fresh", 2), total: 2, page: 1, pages: 1 });
    await user.selectOptions(screen.getByLabelText(/sort/i), "oldest");
    await waitFor(() => expect(screen.getByText(/fresh Candidate 0/)).toBeInTheDocument());

    releaseStale?.();
    await waitFor(() => expect(screen.getByText(/fresh Candidate 0/)).toBeInTheDocument());
    expect(screen.queryByText(/stale Candidate 0/)).not.toBeInTheDocument();
  });
});
