import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/account" }));

const store: { token: string | null; hasHydrated: boolean } = { token: null, hasHydrated: true };
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel?: (s: typeof store) => unknown) => (sel ? sel(store) : store),
}));

import { RequireAuth } from "../AppShell";
import { clearSignInDestination, setSignInDestination, signInUrl } from "@/lib/session";

beforeEach(() => {
  router.replace.mockReset();
  clearSignInDestination();
});

describe("the sign-in guard", () => {
  it("sends a signed-out visitor to /login", () => {
    store.token = null;
    render(<RequireAuth>page</RequireAuth>);
    expect(router.replace).toHaveBeenCalledWith("/login");
  });

  it("goes where the sign-out asked, instead of replacing it with a bare /login", () => {
    // The bug: deleting an account landed on /login without its confirmation,
    // because this redirect ran last.
    store.token = null;
    setSignInDestination("/login?deleted=1");
    render(<RequireAuth>page</RequireAuth>);
    expect(router.replace).toHaveBeenCalledWith("/login?deleted=1");
    expect(router.replace).not.toHaveBeenCalledWith("/login");
  });

  it("keeps the 'session ended' notice for an expired session", () => {
    store.token = null;
    signInUrl();
    render(<RequireAuth>page</RequireAuth>);
    expect(router.replace).toHaveBeenCalledWith("/login?session=expired");
  });

  it("forgets the destination once someone is signed in", () => {
    setSignInDestination("/login?deleted=1");
    store.token = "tok";
    render(<RequireAuth>page</RequireAuth>);
    store.token = null;
    router.replace.mockReset();
    render(<RequireAuth>page</RequireAuth>);
    expect(router.replace).toHaveBeenCalledWith("/login");
  });
});
