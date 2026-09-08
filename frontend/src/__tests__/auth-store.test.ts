import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    authAPI: {
      login: vi.fn(),
      signup: vi.fn(),
      oauthVerify: vi.fn(),
      session: vi.fn(),
      logout: vi.fn().mockResolvedValue({ status: "ok" }),
    },
  };
});

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { signOut: vi.fn() } },
}));

import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { supabase } from "@/lib/supabase";

describe("auth store", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: null,
      token: null,
      isLoading: false,
      error: null,
      requiresEmailConfirmation: false,
    });
    vi.clearAllMocks();
  });

  it("stores the token and user on successful login", async () => {
    (authAPI.login as ReturnType<typeof vi.fn>).mockResolvedValue({
      access_token: "tok-abc",
      user: { id: "u1", email: "a@b.com", full_name: "Ada" },
    });

    await useAuthStore.getState().login("a@b.com", "pw");

    const state = useAuthStore.getState();
    expect(state.token).toBe("tok-abc");
    expect(state.user?.email).toBe("a@b.com");
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("clears token/user and sets an error message on failed login", async () => {
    (authAPI.login as ReturnType<typeof vi.fn>).mockRejectedValue(
      new APIError(401, "invalid_credentials", "Wrong email or password."),
    );

    await expect(useAuthStore.getState().login("a@b.com", "wrong")).rejects.toBeInstanceOf(APIError);

    const state = useAuthStore.getState();
    expect(state.token).toBeNull();
    expect(state.user).toBeNull();
    expect(state.error).toBe("Wrong email or password.");
    // isLoading must always be reset, even on failure — a past bug here
    // left the UI stuck showing a spinner after a failed login.
    expect(state.isLoading).toBe(false);
  });

  it("clears state and calls supabase signOut on logout", () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com" } as any, token: "tok-abc" });

    useAuthStore.getState().logout();

    expect(supabase.auth.signOut).toHaveBeenCalledOnce();
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.token).toBeNull();
  });

  it("flags requiresEmailConfirmation without setting a token when signup needs email confirmation", async () => {
    (authAPI.signup as ReturnType<typeof vi.fn>).mockResolvedValue({
      requires_email_confirmation: true,
    });

    const result = await useAuthStore.getState().signup("a@b.com", "pw", "Ada");

    expect(result.requiresEmailConfirmation).toBe(true);
    const state = useAuthStore.getState();
    expect(state.token).toBeNull();
    expect(state.requiresEmailConfirmation).toBe(true);
  });

  it("restoreSession sets token/user and marks sessionChecked on a valid cookie", async () => {
    (authAPI.session as ReturnType<typeof vi.fn>).mockResolvedValue({
      access_token: "tok-from-cookie",
      user: { id: "u1", email: "a@b.com", full_name: "Ada" },
    });

    await useAuthStore.getState().restoreSession();

    const state = useAuthStore.getState();
    expect(state.token).toBe("tok-from-cookie");
    expect(state.user?.email).toBe("a@b.com");
    expect(state.sessionChecked).toBe(true);
  });

  it("restoreSession clears token/user and still marks sessionChecked when there's no valid session", async () => {
    (authAPI.session as ReturnType<typeof vi.fn>).mockRejectedValue(
      new APIError(401, "unauthorized", "No active session."),
    );
    useAuthStore.setState({ token: "stale-token", user: { id: "u1", email: "a@b.com" } as any });

    await useAuthStore.getState().restoreSession();

    const state = useAuthStore.getState();
    expect(state.token).toBeNull();
    expect(state.user).toBeNull();
    // Pages gate their redirect-to-login logic on this flag rather than on
    // hydration alone, since the token is no longer read from localStorage
    // — it must always end up true once the attempt settles, pass or fail.
    expect(state.sessionChecked).toBe(true);
  });

  it("logout calls the backend logout endpoint in addition to clearing local state", () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com" } as any, token: "tok-abc" });

    useAuthStore.getState().logout();

    expect(authAPI.logout).toHaveBeenCalledOnce();
  });
});
