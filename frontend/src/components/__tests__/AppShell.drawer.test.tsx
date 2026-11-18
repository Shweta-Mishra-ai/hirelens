import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let pathname = "/dashboard";
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => pathname,
}));

const store = {
  user: { id: "u1", email: "r@example.com", full_name: "Rec Ruiter" },
  token: "tok",
  hasHydrated: true,
  logout: vi.fn(),
};
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel?: (s: typeof store) => unknown) => (sel ? sel(store) : store),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    billingAPI: { ...actual.billingAPI, usage: () => new Promise(() => {}) },
  };
});

import { AppShell } from "../AppShell";

describe("mobile navigation drawer", () => {
  it("closes when the page changes", async () => {
    pathname = "/dashboard";
    const view = render(<AppShell>content</AppShell>);
    await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getAllByRole("button", { name: "Close navigation" }).length).toBeGreaterThan(0);

    pathname = "/analyze";
    view.rerender(<AppShell>content</AppShell>);
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  });

  it("stays open while the page does not change", async () => {
    pathname = "/dashboard";
    const view = render(<AppShell>content</AppShell>);
    await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    view.rerender(<AppShell>other content</AppShell>);
    expect(screen.getAllByRole("button", { name: "Close navigation" }).length).toBeGreaterThan(0);
  });
});
