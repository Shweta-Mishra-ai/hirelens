/**
 * Page-level integration test: the login flow.
 *
 * The existing suite covered the API client and the auth store in isolation.
 * Neither would have caught a page that renders the form but never wires the
 * submit handler, calls the store but ignores the redirect, or swallows the
 * error instead of showing it — all of which are single-line mistakes that
 * make login unusable while every unit test stays green.
 *
 * Login is also the app's front door: `/` redirects here and every guarded
 * page bounces here. If it is broken, nothing else is reachable.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replace = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push, prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/login",
}));

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { signInWithOAuth: vi.fn(), signOut: vi.fn() } },
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    authAPI: {
      login: vi.fn(),
      signup: vi.fn(),
      session: vi.fn().mockRejectedValue(new actual.APIError(401, "unauthorized", "No session.")),
      me: vi.fn(),
      logout: vi.fn(),
      oauthVerify: vi.fn(),
      forgotPassword: vi.fn(),
    },
  };
});

import LoginPage from "@/app/(auth)/login/page";
import { authAPI, APIError } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

const mockLogin = authAPI.login as ReturnType<typeof vi.fn>;

describe("login page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    useAuthStore.setState({
      user: null,
      token: null,
      isLoading: false,
      error: null,
      sessionChecked: true,
      hasHydrated: true,
    });
  });

  it("renders the email and password fields and a submit button", () => {
    render(<LoginPage />);

    expect(document.querySelector('input[type="email"]')).toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument();
  });

  it("logs in, stores the token, and redirects to the dashboard", async () => {
    const user = userEvent.setup();
    mockLogin.mockResolvedValue({
      access_token: "tok-login-page",
      user: { id: "u1", email: "recruiter@example.com", full_name: "Recruiter" },
    });

    render(<LoginPage />);

    await user.type(document.querySelector('input[type="email"]')!, "recruiter@example.com");
    await user.type(document.querySelector('input[type="password"]')!, "hunter22");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith("recruiter@example.com", "hunter22"));

    // The token has to reach the store, or every subsequent page 401s.
    await waitFor(() => expect(useAuthStore.getState().token).toBe("tok-login-page"));
    // ...and the user has to actually get sent somewhere.
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the server's error message and does not redirect on a failed login", async () => {
    const user = userEvent.setup();
    mockLogin.mockRejectedValue(
      new APIError(401, "invalid_credentials", "Incorrect email or password."),
    );

    render(<LoginPage />);

    await user.type(document.querySelector('input[type="email"]')!, "recruiter@example.com");
    await user.type(document.querySelector('input[type="password"]')!, "wrong");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    // The real message, not a generic "something went wrong" — a wrong
    // password and a down server need to be distinguishable.
    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("does not call the API when the form is submitted empty", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: "Sign In" }));

    expect(mockLogin).not.toHaveBeenCalled();
  });

  it("redirects an already-authenticated visitor straight to the dashboard", async () => {
    useAuthStore.setState({ token: "existing-token", sessionChecked: true });

    render(<LoginPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("does not redirect before the session check has settled", async () => {
    // sessionChecked=false is the window where restoreSession() is still in
    // flight. Redirecting on `!token` here would bounce a logged-in user to
    // /login on every reload — the exact bug the flag exists to prevent.
    useAuthStore.setState({ token: null, sessionChecked: false });

    render(<LoginPage />);

    await new Promise((r) => setTimeout(r, 50));
    expect(replace).not.toHaveBeenCalled();
  });
});
