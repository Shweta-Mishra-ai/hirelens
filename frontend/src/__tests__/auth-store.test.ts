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
      me: vi.fn(),
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
      sessionChecked: false,
    });
    // The store keeps a per-tab token stash in sessionStorage as the
    // fallback for browsers that drop the cross-site session cookie. It
    // survives between tests in the same jsdom instance, so clear it or one
    // test's login silently satisfies the next test's restore.
    window.sessionStorage.clear();
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

  it("restoreSession falls back to the sessionStorage stash when the cookie is dropped", async () => {
    // The real scenario: Safari / Firefox strict / Chrome Incognito block
    // the cross-site session cookie, so /auth/session 401s on every reload.
    // Before the stash existed this logged the user out on every refresh.
    (authAPI.session as ReturnType<typeof vi.fn>).mockRejectedValue(
      new APIError(401, "unauthorized", "No active session."),
    );
    (authAPI.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "u1",
      email: "a@b.com",
    });

    (authAPI.login as ReturnType<typeof vi.fn>).mockResolvedValue({
      access_token: "tok-stashed",
      user: { id: "u1", email: "a@b.com", full_name: "Ada" },
    });
    await useAuthStore.getState().login("a@b.com", "pw");

    // Simulate a page reload: in-memory state is gone, storage is not.
    useAuthStore.setState({ token: null, user: null, sessionChecked: false });

    await useAuthStore.getState().restoreSession();

    const state = useAuthStore.getState();
    expect(authAPI.me).toHaveBeenCalledWith("tok-stashed");
    expect(state.token).toBe("tok-stashed");
    expect(state.user?.email).toBe("a@b.com");
    expect(state.sessionChecked).toBe(true);
  });

  it("restoreSession discards a stashed token the server rejects", async () => {
    // A stale/expired/tampered stash must log the user out cleanly rather
    // than leaving a token in place that 401s on every subsequent call.
    window.sessionStorage.setItem("hirelens-token", "expired-token");
    (authAPI.session as ReturnType<typeof vi.fn>).mockRejectedValue(
      new APIError(401, "unauthorized", "No active session."),
    );
    (authAPI.me as ReturnType<typeof vi.fn>).mockRejectedValue(
      new APIError(401, "unauthorized", "Token expired."),
    );

    await useAuthStore.getState().restoreSession();

    const state = useAuthStore.getState();
    expect(state.token).toBeNull();
    expect(state.user).toBeNull();
    expect(state.sessionChecked).toBe(true);
    expect(window.sessionStorage.getItem("hirelens-token")).toBeNull();
  });

  it("logout clears the stashed token so a reload cannot resurrect the session", () => {
    window.sessionStorage.setItem("hirelens-token", "tok-abc");
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com" } as any, token: "tok-abc" });

    useAuthStore.getState().logout();

    expect(window.sessionStorage.getItem("hirelens-token")).toBeNull();
  });

  it("logout calls the backend logout endpoint in addition to clearing local state", () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com" } as any, token: "tok-abc" });

    useAuthStore.getState().logout();

    expect(authAPI.logout).toHaveBeenCalledOnce();
  });
});
