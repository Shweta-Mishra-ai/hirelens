import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const plansMock = vi.fn();
const mineMock = vi.fn();
const submitMock = vi.fn();
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn(() => Promise.resolve("data:image/png;base64,QR")) } }));

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/upgrade" }));
const store = { user: { id: "u1", email: "r@example.com", full_name: "R" }, token: "tok", hasHydrated: true, logout: vi.fn() };
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel?: (s: typeof store) => unknown) => (sel ? sel(store) : store),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    billingAPI: {
      usage: () => new Promise(() => {}),
      plans: (...a: unknown[]) => plansMock(...a),
      myPayments: (...a: unknown[]) => mineMock(...a),
      submitPayment: (...a: unknown[]) => submitMock(...a),
    },
  };
});

import UpgradePage, { upiLink } from "../page";

const usage = {
  plan: "free", period_start: "", period_end: "2026-12-01T00:00:00Z", used: 20, in_progress: 0,
  limit: 20, remaining: 0, unlimited: false, upgrade_url: "/upgrade", plan_expires_at: null,
};
const offered = {
  upi_id: "hirelens@okbank", payee_name: "HireLens Pvt Ltd", period_days: 30, usage,
  plans: [{ plan: "pro", price_inr: 499, monthly_analyses: 300 }, { plan: "team", price_inr: 1499, monthly_analyses: null }],
};

beforeEach(() => {
  [plansMock, mineMock, submitMock].forEach((m) => m.mockReset());
  mineMock.mockResolvedValue({ payments: [] });
});

describe("upi link", () => {
  it("is the NPCI deep link with every part encoded, spaces as %20", () => {
    expect(upiLink("a.b@okbank", "Acme & Co", 499, "HireLens Pro")).toBe(
      "upi://pay?pa=a.b%40okbank&pn=Acme%20%26%20Co&am=499.00&cu=INR&tn=HireLens%20Pro",
    );
  });
});

describe("upgrade page", () => {
  it("shows the plans, the UPI ID and a QR for the selected plan", async () => {
    plansMock.mockResolvedValue(offered);
    render(<UpgradePage />);
    expect(await screen.findByText("Pay ₹499 for Pro")).toBeInTheDocument();
    expect(screen.getByText("hirelens@okbank")).toBeInTheDocument();
    expect(await screen.findByAltText(/UPI QR code: pay ₹499/)).toHaveAttribute("src", "data:image/png;base64,QR");
    await userEvent.click(screen.getByRole("radio", { name: /Team/ }));
    expect(screen.getByText("Pay ₹1,499 for Team")).toBeInTheDocument();
  });

  it("sends the reference and confirms it was received", async () => {
    plansMock.mockResolvedValue(offered);
    submitMock.mockResolvedValue({ id: "p1", status: "pending" });
    render(<UpgradePage />);
    await userEvent.type(await screen.findByLabelText("Transaction reference (UTR)"), "402156789012");
    mineMock.mockResolvedValue({
      payments: [{ id: "p1", plan: "pro", amount_inr: 499, method: "upi", reference: "402156789012",
        status: "pending", note: null, created_at: "2026-11-19T10:00:00Z", decided_at: null }],
    });
    await userEvent.click(screen.getByRole("button", { name: /I've paid/ }));
    await waitFor(() => expect(submitMock).toHaveBeenCalledWith("pro", "402156789012", "tok"));
    expect(await screen.findByText(/we've got your payment details/)).toBeInTheDocument();
    expect(await screen.findByText("Waiting for verification")).toBeInTheDocument();
  });

  it("shows the server's reason when a reference is refused", async () => {
    const { APIError } = await import("@/lib/api");
    plansMock.mockResolvedValue(offered);
    submitMock.mockRejectedValue(new APIError(409, "conflict", "This transaction reference has already been submitted."));
    render(<UpgradePage />);
    await userEvent.type(await screen.findByLabelText("Transaction reference (UTR)"), "402156789012");
    await userEvent.click(screen.getByRole("button", { name: /I've paid/ }));
    expect(await screen.findByText(/already been submitted/)).toBeInTheDocument();
  });

  it("does not offer a second claim while one is waiting", async () => {
    plansMock.mockResolvedValue(offered);
    mineMock.mockResolvedValue({
      payments: [{ id: "p1", plan: "pro", amount_inr: 499, method: "upi", reference: "1", status: "pending",
        note: null, created_at: "2026-11-19T10:00:00Z", decided_at: null }],
    });
    render(<UpgradePage />);
    expect(await screen.findByText(/already have a payment waiting/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Transaction reference (UTR)")).not.toBeInTheDocument();
  });

  it("says upgrades are not available when nothing is for sale", async () => {
    plansMock.mockResolvedValue({ ...offered, upi_id: null, plans: [] });
    render(<UpgradePage />);
    expect(await screen.findByText(/Upgrades aren't available in the app yet/)).toBeInTheDocument();
  });
});
