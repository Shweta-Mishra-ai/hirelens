import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

/**
 * What the owner of a candidate file can do on it, and what a teammate it is
 * shared with sees instead. The server enforces the same split; these tests
 * keep the page from offering a teammate buttons that can only fail.
 */
const getMock = vi.fn();
const deleteMock = vi.fn();
const shareMock = vi.fn();
const unshareMock = vi.fn();
const search = new URLSearchParams({ id: "3f2a9c1e-7b4d-4e8a-9c1f-0a2b3c4d5e6f" });

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
    reportsAPI: {
      ...actual.reportsAPI,
      get: (...args: unknown[]) => getMock(...args),
      delete: (...args: unknown[]) => deleteMock(...args),
    },
    teamsAPI: {
      ...actual.teamsAPI,
      list: () => Promise.resolve({ teams: [{ id: "t1", name: "Platform Hiring" }] }),
    },
    collaborationAPI: {
      ...actual.collaborationAPI,
      listComments: () => Promise.resolve({ comments: [] }),
      listVotes: () => Promise.resolve({ tally: { advance: 0, reject: 0, maybe: 0 }, my_vote: null, votes: [] }),
      share: (...args: unknown[]) => shareMock(...args),
      unshare: (...args: unknown[]) => unshareMock(...args),
    },
    copilotAPI: { ...actual.copilotAPI, get: () => Promise.resolve({ copilot: {} }) },
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
  recruiter_decision: "advance",
  team_id: null as string | null,
};

beforeEach(() => {
  getMock.mockReset();
  deleteMock.mockReset();
  shareMock.mockReset();
  unshareMock.mockReset();
  router.replace.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the owner", () => {
  it("can delete the file after confirming, and lands on the dashboard", async () => {
    getMock.mockResolvedValue({ ...REPORT, is_owner: true });
    deleteMock.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ReportPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(REPORT.id, "tok"));
    expect(router.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("keeps the file when the confirmation is cancelled", async () => {
    getMock.mockResolvedValue({ ...REPORT, is_owner: true });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ReportPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it("is told when the delete fails, and stays on the file", async () => {
    const { APIError } = await import("@/lib/api");
    getMock.mockResolvedValue({ ...REPORT, is_owner: true });
    deleteMock.mockRejectedValue(new APIError(503, "storage_write_failed", "That report could not be deleted. It is unchanged — please try again."));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ReportPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    expect(await screen.findByText(/could not be deleted/)).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("records decisions and can email the candidate", async () => {
    getMock.mockResolvedValue({ ...REPORT, is_owner: true });
    render(<ReportPage />);
    expect(await screen.findByText("Your decision")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Email the candidate" })).toBeInTheDocument();
  });

  it("treats a report from an older API, with no is_owner, as theirs", async () => {
    getMock.mockResolvedValue({ ...REPORT });
    render(<ReportPage />);
    expect(await screen.findByRole("button", { name: "Delete file" })).toBeInTheDocument();
  });

  it("can stop sharing from the Discuss tab", async () => {
    getMock.mockResolvedValue({ ...REPORT, is_owner: true, team_id: "t1" });
    unshareMock.mockResolvedValue({ status: "unshared" });
    render(<ReportPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Discuss/ }));
    const select = await screen.findByLabelText("Team");
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe("t1"));
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => expect(unshareMock).toHaveBeenCalledWith(REPORT.id, "tok"));
    expect(shareMock).not.toHaveBeenCalled();
  });
});

describe("a teammate the file is shared with", () => {
  it("sees the owner's decision but no decision buttons, email, delete or sharing", async () => {
    getMock.mockResolvedValue({ ...REPORT, is_owner: false, team_id: "t1" });
    render(<ReportPage />);
    expect(await screen.findByText("Shared with you")).toBeInTheDocument();
    expect(screen.getByText("Advance")).toBeInTheDocument();
    expect(screen.queryByText("Your decision")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Email the candidate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete file" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Discuss/ }));
    expect(await screen.findByText("Shared with your team")).toBeInTheDocument();
    expect(screen.queryByLabelText("Team")).not.toBeInTheDocument();
  });

  it("is told when no decision has been recorded yet", async () => {
    getMock.mockResolvedValue({ ...REPORT, is_owner: false, recruiter_decision: null });
    render(<ReportPage />);
    expect(await screen.findByText("No decision yet.")).toBeInTheDocument();
  });
});
