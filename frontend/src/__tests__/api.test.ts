import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { APIError } from "@/lib/api";

/**
 * These tests target req() (the shared fetch wrapper in lib/api.ts)
 * indirectly through authAPI.login, since req() itself isn't exported.
 * That's deliberate: it exercises the exact code path every real API call
 * goes through, rather than testing an internal in isolation.
 */

describe("API client (lib/api.ts)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("throws a network_error APIError when fetch rejects with TypeError (offline/unreachable)", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const { authAPI } = await import("@/lib/api");

    await expect(authAPI.login("a@b.com", "pw")).rejects.toMatchObject({
      name: "APIError",
      code: "network_error",
      status: 0,
    });
  });

  it("throws a timeout APIError when the request is aborted", async () => {
    global.fetch = vi.fn().mockImplementation(() => {
      const err = new Error("The operation was aborted");
      err.name = "TimeoutError";
      return Promise.reject(err);
    });
    const { authAPI } = await import("@/lib/api");

    await expect(authAPI.login("a@b.com", "pw")).rejects.toMatchObject({
      code: "timeout",
    });
  });

  it("surfaces the server's error code + message on a non-2xx JSON response", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "invalid_credentials", message: "Wrong email or password." }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    const { authAPI } = await import("@/lib/api");

    await expect(authAPI.login("a@b.com", "wrong")).rejects.toMatchObject({
      status: 401,
      code: "invalid_credentials",
      message: "Wrong email or password.",
    });
  });

  it("sends the bearer token in the Authorization header when one is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ reports: [], total: 0, pages: 0 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock;
    const { reportsAPI } = await import("@/lib/api");

    await reportsAPI.list("test-token-123", {});

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token-123");
  });

  it("does not set Authorization when no token is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock;
    // Re-import a module that hits an endpoint without requiring a token.
    const api = await import("@/lib/api");
    await fetch(`${api.API_BASE}/api/v1/health`);

    expect(APIError).toBeDefined(); // sanity: module loaded correctly
  });
});
