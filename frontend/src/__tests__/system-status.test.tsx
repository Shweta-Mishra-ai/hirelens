/**
 * The dashboard's status pill.
 *
 * It used to be a hardcoded `<Badge tone="success" dot>All systems
 * operational</Badge>` — literally a constant. It reported green while the
 * LLM key was missing, while storage had fallen back to container-local
 * SQLite that gets wiped on every redeploy, and while the API was down
 * entirely. A status indicator that can only say "fine" is worse than none:
 * it tells a recruiter their candidate data is safe at the moment it isn't.
 *
 * These tests exist so it can never quietly become a constant again. Each one
 * pins a state that MUST be visibly different from "operational".
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const check = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, healthAPI: { check: () => check(), diagnostics: vi.fn() } };
});

import { SystemStatus } from "@/components/ui/SystemStatus";

const HEALTHY = {
  status: "ok",
  version: "1.0.0",
  env: "production",
  llm_ready: true,
  storage_mode: "supabase" as const,
  storage_warning: null,
  config_warnings: [],
  services: {},
};

describe("SystemStatus", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reports operational only when the API says everything is fine", async () => {
    check.mockResolvedValue(HEALTHY);

    render(<SystemStatus />);

    expect(await screen.findByText("All systems operational")).toBeInTheDocument();
  });

  it("warns about temporary storage instead of claiming everything is fine", async () => {
    // The scenario that matters most: Supabase env vars never set in the
    // hosting dashboard. Every account and report is on a disk that gets
    // wiped on the next redeploy, and the old badge said "operational".
    check.mockResolvedValue({
      ...HEALTHY,
      status: "degraded",
      storage_mode: "local_fallback" as const,
      storage_warning: "Accounts/reports are on local SQLite and will be lost.",
    });

    render(<SystemStatus />);

    expect(await screen.findByText("Temporary storage")).toBeInTheDocument();
    expect(screen.queryByText("All systems operational")).not.toBeInTheDocument();
  });

  it("shows degraded when the backend reports a config warning", async () => {
    check.mockResolvedValue({
      ...HEALTHY,
      status: "degraded",
      config_warnings: [
        { code: "cors_localhost_only", message: "ALLOWED_ORIGINS is localhost only." },
      ],
    });

    render(<SystemStatus />);

    const badge = await screen.findByText("Degraded");
    expect(badge).toBeInTheDocument();
    // The detail has to be reachable, not just the one-word label.
    expect(badge.closest("span")).toHaveAttribute(
      "title",
      "ALLOWED_ORIGINS is localhost only.",
    );
  });

  it("shows degraded when no AI provider is configured", async () => {
    check.mockResolvedValue({ ...HEALTHY, status: "degraded", llm_ready: false });

    render(<SystemStatus />);

    expect(await screen.findByText("Degraded")).toBeInTheDocument();
  });

  it("says the API is unreachable rather than claiming it is operational", async () => {
    check.mockRejectedValue(new Error("network down"));

    render(<SystemStatus />);

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
  });

  it("renders nothing at all until the health response arrives", async () => {
    check.mockReturnValue(new Promise(() => {})); // never resolves

    const { container } = render(<SystemStatus />);

    // No optimistic green badge while the answer is still unknown.
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});
