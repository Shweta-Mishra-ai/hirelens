import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { UsageMeter } from "@/components/UsageMeter";
import { useAuthStore } from "@/store/auth";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

function usage(over: Record<string, unknown> = {}) {
  return {
    plan: "free",
    period_start: "2026-11-01T00:00:00+00:00",
    period_end: "2026-12-01T00:00:00+00:00",
    used: 3,
    in_progress: 0,
    limit: 25,
    remaining: 22,
    unlimited: false,
    upgrade_url: "https://pay.example.com/pro",
    ...over,
  };
}

function serve(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
    ),
  );
}

beforeEach(() => {
  useAuthStore.setState({ token: "t" } as never);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UsageMeter", () => {
  it("shows the month's usage against the plan", async () => {
    serve(usage());
    render(<UsageMeter collapsed={false} />);
    expect(await screen.findByText("3/25")).toBeInTheDocument();
    expect(screen.getByText(/22 left this month/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upgrade/i })).toHaveAttribute(
      "href",
      "https://pay.example.com/pro",
    );
  });

  it("says plainly when the allowance is used up", async () => {
    serve(usage({ used: 25, remaining: 0 }));
    render(<UsageMeter collapsed={false} />);
    expect(await screen.findByText(/All analyses used/)).toBeInTheDocument();
  });

  it("renders nothing for an unlimited plan with nothing to upgrade to", async () => {
    serve(usage({ unlimited: true, limit: null, remaining: null, upgrade_url: null }));
    const { container } = render(<UsageMeter collapsed={false} />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("stays out of the way if usage cannot be loaded", async () => {
    serve({ error: "database_unavailable", message: "x" }, 503);
    const { container } = render(<UsageMeter collapsed={false} />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
