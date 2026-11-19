import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const checkMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, healthAPI: { check: (...a: unknown[]) => checkMock(...a) } };
});
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { signInWithOAuth: vi.fn() } } }));

async function load() {
  vi.resetModules();
  return (await import("../useGoogleAuth")).useGoogleAuth;
}

beforeEach(() => {
  checkMock.mockReset();
  checkMock.mockResolvedValue({ google_auth_ready: true });
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe("useGoogleAuth", () => {
  it("knows on the first render that the browser half is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "");
    const useGoogleAuth = await load();
    const { result } = renderHook(() => useGoogleAuth());
    expect(result.current.state.status).toBe("unconfigured");
    // Still wakes the API while the person types — once.
    await waitFor(() => expect(checkMock).toHaveBeenCalledTimes(1));
  });

  it("asks the server once, and uses that answer, when the browser half is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://abc.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "eyJ-real-looking-key");
    const useGoogleAuth = await load();
    const { result } = renderHook(() => useGoogleAuth());
    expect(result.current.state.status).toBe("checking");
    await waitFor(() => expect(result.current.state.status).toBe("ready"));
    expect(checkMock).toHaveBeenCalledTimes(1);
  });

  it("reports the server half as missing when the API says so", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://abc.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "eyJ-real-looking-key");
    checkMock.mockResolvedValue({ google_auth_ready: false });
    const useGoogleAuth = await load();
    const { result } = renderHook(() => useGoogleAuth());
    await waitFor(() => expect(result.current.state.status).toBe("unconfigured"));
  });
});
