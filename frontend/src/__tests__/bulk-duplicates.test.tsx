/**
 * Bulk page — duplicate-cluster rendering.
 *
 * This is a regression test for a bug that shipped and was only caught by
 * reading the code: the page rendered `c.candidates.length` and
 * `c.candidates.map(x => x.candidate_name)`, but the API returns
 * `{ similarity, members: [{ id, name }] }`. Neither field existed on the
 * real response, so the moment "Check Duplicates" actually FOUND a duplicate
 * — the only time this branch runs at all — it rendered broken text or threw.
 *
 * It compiled because the cluster was typed `any`, and no test ever rendered
 * a non-empty result. Hence this test: it drives the found-a-duplicate path
 * with the real response shape and asserts on the names a recruiter reads.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replace = vi.fn();
const router = { replace, push: vi.fn(), prefetch: vi.fn(), back: vi.fn(), refresh: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/bulk",
}));

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { signInWithOAuth: vi.fn(), signOut: vi.fn() } },
}));

const checkDuplicates = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    bulkAPI: { ...actual.bulkAPI, checkDuplicates: (...a: unknown[]) => checkDuplicates(...a) },
    authAPI: {
      login: vi.fn(),
      signup: vi.fn(),
      session: vi.fn().mockResolvedValue({
        access_token: "tok",
        user: { id: "u1", email: "r@example.com", full_name: "Recruiter" },
      }),
      me: vi.fn(),
      logout: vi.fn(),
      oauthVerify: vi.fn(),
    },
  };
});

// A finished batch, so the duplicate-check button is actually reachable.
// Shape must match the hook's real `BulkState` discriminated union.
vi.mock("@/hooks/useBulkAnalysis", () => ({
  useBulkAnalysis: () => ({
    state: {
      phase: "done",
      batch: {
        batch_id: "batch-1",
        total: 2,
        queued: 0,
        running: 0,
        complete: 2,
        failed: 0,
        is_done: true,
        jobs: [],
        ranking: [
          { rank: 1, report_id: "r1", file_name: "a.pdf", candidate_name: "Ada Lovelace", overall_score: 88, recommendation: "recommended" },
          { rank: 2, report_id: "r2", file_name: "b.pdf", candidate_name: "Ada L.", overall_score: 84, recommendation: "recommended" },
        ],
      },
    },
    upload: vi.fn(),
    uploadFromAts: vi.fn(),
    exportCsv: vi.fn(),
    exporting: false,
    exportError: null,
    reset: vi.fn(),
  }),
}));

import BulkPage from "@/app/bulk/page";
import { useAuthStore } from "@/store/auth";

describe("bulk page duplicate detection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    useAuthStore.setState({
      user: { id: "u1", email: "r@example.com", full_name: "Recruiter" },
      token: "tok",
      sessionChecked: true,
      hasHydrated: true,
      isLoading: false,
      error: null,
    });
  });

  it("renders the names inside a duplicate cluster", async () => {
    const user = userEvent.setup();
    // The real DuplicateCheckResult shape from GET /bulk/{id}/duplicates.
    checkDuplicates.mockResolvedValue({
      batch_id: "batch-1",
      candidates_compared: 2,
      clusters: [
        { similarity: 0.94, members: [{ id: "r1", name: "Ada Lovelace" }, { id: "r2", name: "Ada L." }] },
      ],
      note: "",
    });

    render(<BulkPage />);

    await user.click(await screen.findByText("Check Duplicates"));

    // The member names, joined — this is what the broken version rendered as
    // `undefined & undefined` (or threw on `c.candidates.length`).
    expect(await screen.findByText(/Ada Lovelace & Ada L\./)).toBeInTheDocument();
    // Count and similarity come off the same object.
    expect(screen.getByText(/Duplicate Group \(2, 94% similar\)/)).toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  it("reports 'no duplicates' rather than an empty panel when none are found", async () => {
    const user = userEvent.setup();
    checkDuplicates.mockResolvedValue({
      batch_id: "batch-1",
      candidates_compared: 2,
      clusters: [],
      note: "",
    });

    render(<BulkPage />);
    await user.click(await screen.findByText("Check Duplicates"));

    expect(await screen.findByText(/No duplicate candidates detected/)).toBeInTheDocument();
  });

  it("shows the server's message when the duplicate check fails", async () => {
    const user = userEvent.setup();
    const { APIError } = await import("@/lib/api");
    checkDuplicates.mockRejectedValue(new APIError(503, "unavailable", "Duplicate service is down."));

    render(<BulkPage />);
    await user.click(await screen.findByText("Check Duplicates"));

    await waitFor(() =>
      expect(screen.getByText("Duplicate service is down.")).toBeInTheDocument(),
    );
  });
});
