import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const deleteMock = vi.fn();
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/account",
}));

const store = {
  user: { id: "u1", email: "rec@example.com", full_name: "Rec Ruiter" },
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
    authAPI: {
      ...actual.authAPI,
      deleteAccount: (...a: unknown[]) => deleteMock(...a),
      logoutAll: vi.fn(),
      me: () => Promise.resolve({ id: "u1", email: "rec@example.com", is_admin: false }),
    },
    billingAPI: {
      usage: () =>
        Promise.resolve({
          plan: "free", period_start: "2026-11-01T00:00:00Z", period_end: "2026-12-01T00:00:00Z",
          used: 3, in_progress: 0, limit: 20, remaining: 17, unlimited: false, upgrade_url: null,
        }),
    },
  };
});

import AccountPage from "../page";

beforeEach(() => {
  deleteMock.mockReset();
  router.replace.mockReset();
  store.logout.mockReset();
});

describe("account page", () => {
  it("shows the plan and this month's usage", async () => {
    render(<AccountPage />);
    // "Free plan" also appears in the sidebar's usage meter; this line is the page's own.
    expect(await screen.findByText(/3 of 20 analyses used this month/)).toBeInTheDocument();
    expect(screen.getAllByText("Free plan").length).toBeGreaterThan(0);
  });

  it("will not delete until the account's email is typed", async () => {
    render(<AccountPage />);
    const button = screen.getByRole("button", { name: /Delete my account/ });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/to confirm/), "someone@example.com");
    expect(button).toBeDisabled();
    await userEvent.clear(screen.getByLabelText(/to confirm/));
    await userEvent.type(screen.getByLabelText(/to confirm/), "REC@example.com");
    expect(button).toBeEnabled();
  });

  it("deletes, signs out and says so on the sign-in page", async () => {
    deleteMock.mockResolvedValue({ status: "deleted", message: "ok" });
    render(<AccountPage />);
    await userEvent.type(screen.getByLabelText(/to confirm/), "rec@example.com");
    await userEvent.click(screen.getByRole("button", { name: /Delete my account/ }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?deleted=1"));
    expect(deleteMock).toHaveBeenCalledWith("rec@example.com", "tok");
    expect(store.logout).toHaveBeenCalled();
  });

  it("stays signed in and shows the server's reason when deletion is refused", async () => {
    const { APIError } = await import("@/lib/api");
    deleteMock.mockRejectedValue(new APIError(409, "conflict", "1 analysis is still running. Wait for it to finish, then delete your account."));
    render(<AccountPage />);
    await userEvent.type(screen.getByLabelText(/to confirm/), "rec@example.com");
    await userEvent.click(screen.getByRole("button", { name: /Delete my account/ }));
    expect(await screen.findByText(/still running/)).toBeInTheDocument();
    expect(store.logout).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });
});
