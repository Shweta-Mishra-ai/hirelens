import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APIError,
  USAGE_CHANGED_EVENT,
  bulkAPI,
  reportsAPI,
  toAPIError,
  upgradeUrlOf,
} from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("quota errors", () => {
  it("carry the upgrade link the server sent", () => {
    const err = toAPIError(402, {
      error: "quota_exceeded",
      message: "You've used all 25 analyses included in your free plan this month.",
      upgrade_url: "https://pay.example.com/pro",
    });
    expect(err.code).toBe("quota_exceeded");
    expect(upgradeUrlOf(err)).toBe("https://pay.example.com/pro");
  });

  it("have no upgrade link when the operator configured none", () => {
    expect(upgradeUrlOf(toAPIError(402, { error: "quota_exceeded", message: "x" }))).toBeNull();
    expect(upgradeUrlOf(new Error("not an API error"))).toBeNull();
  });

  it("tell the usage meter to refresh", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(402, { error: "quota_exceeded", message: "Used up." })),
    );
    const heard = vi.fn();
    window.addEventListener(USAGE_CHANGED_EVENT, heard);
    await expect(bulkAPI.upload([new File(["%PDF"], "a.pdf")], "t")).rejects.toBeInstanceOf(APIError);
    window.removeEventListener(USAGE_CHANGED_EVENT, heard);
    expect(heard).toHaveBeenCalledTimes(1);
  });
});

describe("CSV export", () => {
  it("surfaces the server's own explanation instead of a generic failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, {
          error: "database_unavailable",
          message: "The export could not be built because the database did not answer.",
        }),
      ),
    );
    const err = await reportsAPI.downloadAllCsv("t").catch((e) => e);
    expect(err).toBeInstanceOf(APIError);
    expect(err.status).toBe(503);
    expect(err.message).toContain("database did not answer");
  });

  it("reports a network failure as one", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await bulkAPI.downloadCsv("b1", "t").catch((e) => e);
    expect(err).toBeInstanceOf(APIError);
    expect(err.code).toBe("network_error");
  });
});

describe("upload timeouts", () => {
  it("give a batch upload far longer than the default minute", async () => {
    const spy = vi.spyOn(AbortSignal, "timeout");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(202, { batch_id: "b", total: 1, accepted: 1, rejected: 0 })),
    );
    await bulkAPI.upload([new File(["%PDF"], "a.pdf")], "t");
    expect(spy).toHaveBeenCalled();
    expect(spy.mock.calls[0][0]).toBeGreaterThanOrEqual(10 * 60_000);
  });
});
