import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const meMock = vi.fn();
const accountsMock = vi.fn();
const accountMock = vi.fn();
const setPlanMock = vi.fn();

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/admin" }));

const store = {
  user: { id: "op", email: "ops@example.com", full_name: "Ops" },
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
    authAPI: { ...actual.authAPI, me: (...a: unknown[]) => meMock(...a) },
    adminAPI: {
      accounts: (...a: unknown[]) => accountsMock(...a),
      account: (...a: unknown[]) => accountMock(...a),
      setPlan: (...a: unknown[]) => setPlanMock(...a),
    },
    billingAPI: { usage: () => new Promise(() => {}) },
  };
});

import AdminPage from "../page";

const usage = (plan: string) => ({
  plan, period_start: "", period_end: "", used: 4, in_progress: 0, limit: 20, remaining: 16,
  unlimited: false, upgrade_url: null,
});

beforeEach(() => {
  [meMock, accountsMock, accountMock, setPlanMock].forEach((m) => m.mockReset());
  accountsMock.mockResolvedValue({
    accounts: [{ user_id: "c1", email: "cust@acme.com", full_name: "Cust", company: "Acme", created_at: null, plan: "free" }],
  });
  accountMock.mockResolvedValue({ user_id: "c1", email: "cust@acme.com", full_name: "Cust", company: "Acme", created_at: null, usage: usage("free") });
});

describe("operator page", () => {
  it("refuses non-operators without calling the operator API", async () => {
    meMock.mockResolvedValue({ id: "u", email: "u@example.com", is_admin: false });
    render(<AdminPage />);
    expect(await screen.findByText("Operators only")).toBeInTheDocument();
    expect(accountsMock).not.toHaveBeenCalled();
  });

  it("lists accounts, opens one, and changes its plan after confirmation", async () => {
    meMock.mockResolvedValue({ id: "op", email: "ops@example.com", is_admin: true });
    setPlanMock.mockResolvedValue({ status: "ok" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AdminPage />);

    await userEvent.click(await screen.findByRole("button", { name: /cust@acme.com/ }));
    expect(await screen.findByText(/4 of 20 analyses/)).toBeInTheDocument();

    accountMock.mockResolvedValue({ user_id: "c1", email: "cust@acme.com", full_name: "Cust", company: "Acme", created_at: null, usage: usage("pro") });
    await userEvent.click(screen.getByRole("button", { name: "Pro" }));
    await waitFor(() => expect(setPlanMock).toHaveBeenCalledWith("cust@acme.com", "pro", "tok"));
    expect(await screen.findByText(/is now on the Pro plan/)).toBeInTheDocument();
  });

  it("does nothing when the operator cancels the confirmation", async () => {
    meMock.mockResolvedValue({ id: "op", email: "ops@example.com", is_admin: true });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<AdminPage />);
    await userEvent.click(await screen.findByRole("button", { name: /cust@acme.com/ }));
    await screen.findByText(/4 of 20 analyses/);
    await userEvent.click(screen.getByRole("button", { name: "Team" }));
    expect(setPlanMock).not.toHaveBeenCalled();
  });

  it("searches by email", async () => {
    meMock.mockResolvedValue({ id: "op", email: "ops@example.com", is_admin: true });
    render(<AdminPage />);
    await screen.findByRole("button", { name: /cust@acme.com/ });
    await userEvent.type(screen.getByLabelText("Search by email"), "acme");
    await userEvent.click(screen.getByRole("button", { name: /Search/ }));
    await waitFor(() => expect(accountsMock).toHaveBeenLastCalledWith("tok", "acme"));
  });
});
