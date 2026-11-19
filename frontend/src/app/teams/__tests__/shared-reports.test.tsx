import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * The team page lists the candidate files shared with the team, so a
 * teammate can find one without being sent its link.
 */
const reportsMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/teams/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useGoogleAuth", () => ({
  consumeOAuthFragment: () => Promise.resolve(null),
  useGoogleAuth: () => ({ signIn: vi.fn(), loading: false, error: null }),
}));

const store = {
  user: { id: "u2", email: "ben@example.com", full_name: "Ben Mate" },
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
    teamsAPI: {
      ...actual.teamsAPI,
      list: () => Promise.resolve({ teams: [{ id: "t1", name: "Platform Hiring", my_role: "member" }] }),
      members: () => Promise.resolve({ members: [] }),
      invites: () => Promise.resolve({ invites: [] }),
      reports: (...args: unknown[]) => reportsMock(...args),
    },
    billingAPI: {
      ...actual.billingAPI,
      usage: () => Promise.resolve({ plan: "free", limit: 0, used: 0, remaining: null, upgrade_url: null }),
    },
  };
});

import TeamsPage from "../page";

beforeEach(() => {
  reportsMock.mockReset();
});

describe("files shared with a team", () => {
  it("lists each shared file, who shared it, and links to it", async () => {
    reportsMock.mockResolvedValue({
      reports: [{
        id: "3f2a9c1e-7b4d-4e8a-9c1f-0a2b3c4d5e6f",
        candidate_name: "Priya Sharma",
        file_name: "priya.pdf",
        overall_score: 83,
        recommendation: "recommended",
        recruiter_decision: null,
        created_at: new Date().toISOString(),
        shared_by: "Asha Rao",
        is_mine: false,
      }],
    });
    render(<TeamsPage />);
    const link = await screen.findByRole("link", { name: /Priya Sharma/ });
    expect(link).toHaveAttribute("href", "/report?id=3f2a9c1e-7b4d-4e8a-9c1f-0a2b3c4d5e6f");
    expect(link).toHaveTextContent("Shared by Asha Rao");
    expect(reportsMock).toHaveBeenCalledWith("t1", "tok");
  });

  it("says how to share when nothing is shared yet", async () => {
    reportsMock.mockResolvedValue({ reports: [] });
    render(<TeamsPage />);
    expect(await screen.findByText(/Nothing shared yet/)).toBeInTheDocument();
  });

  it("shows an error instead of an empty list when loading fails", async () => {
    const { APIError } = await import("@/lib/api");
    reportsMock.mockRejectedValue(new APIError(503, "database_unavailable", "The database is not answering."));
    render(<TeamsPage />);
    expect(await screen.findByText("The database is not answering.")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing shared yet/)).not.toBeInTheDocument();
  });
});
