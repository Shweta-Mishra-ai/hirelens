import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

/**
 * Polling lifecycle.
 *
 * The bug this pins: `pollBatch` ran one poll and then started an interval
 * unconditionally. `stopPolling()` inside that first poll was a no-op —
 * `pollRef.current` was still null — so a batch that was already finished on
 * the first call had an interval started immediately afterwards, and went on
 * polling for the full MAX_ATTEMPTS ceiling (240 requests over ten minutes),
 * re-setting React state on every tick.
 */

const status = vi.fn();
const upload = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    bulkAPI: {
      upload: (...a: unknown[]) => upload(...a),
      status: (...a: unknown[]) => status(...a),
      downloadCsv: vi.fn(),
      importFromAts: vi.fn(),
      checkDuplicates: vi.fn(),
    },
  };
});

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { token: string }) => unknown) => selector({ token: "test-token" }),
}));

import { useBulkAnalysis } from "@/hooks/useBulkAnalysis";

const doneBatch = {
  batch_id: "b1",
  total: 1,
  complete: 1,
  failed: 0,
  queued: 0,
  running: 0,
  is_done: true,
  ranking: [],
};

function file() {
  return new File(["x"], "cv.pdf", { type: "application/pdf" });
}

describe("useBulkAnalysis polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    status.mockReset();
    upload.mockReset();
    upload.mockResolvedValue({ batch_id: "b1", total: 1, accepted: 1, rejected: 0 });
  });
  afterEach(() => vi.useRealTimers());

  it("stops immediately when the first poll already reports completion", async () => {
    status.mockResolvedValue(doneBatch);
    const { result } = renderHook(() => useBulkAnalysis());

    await act(async () => {
      await result.current.upload([file()]);
    });

    expect(result.current.state.phase).toBe("done");
    const callsAfterFirstPoll = status.mock.calls.length;
    expect(callsAfterFirstPoll).toBe(1);

    // Ten minutes of wall clock: a leaked interval would fire ~240 times.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    });
    expect(status.mock.calls.length).toBe(callsAfterFirstPoll);
  });

  it("keeps polling while the batch is still running", async () => {
    status
      .mockResolvedValueOnce({ ...doneBatch, complete: 0, is_done: false })
      .mockResolvedValueOnce({ ...doneBatch, complete: 0, is_done: false })
      .mockResolvedValue(doneBatch);

    const { result } = renderHook(() => useBulkAnalysis());
    await act(async () => {
      await result.current.upload([file()]);
    });
    expect(result.current.state.phase).toBe("processing");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(status.mock.calls.length).toBeGreaterThan(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    // `waitFor` polls on real timers, which never advance here — assert
    // directly instead, since advanceTimersByTimeAsync already flushed the
    // pending state update.
    expect(result.current.state.phase).toBe("done");

    const settled = status.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(status.mock.calls.length).toBe(settled);
  });

  it("stops polling when the first poll returns 401", async () => {
    const { APIError } = await import("@/lib/api");
    status.mockRejectedValue(new APIError(401, "unauthorized", "Session expired"));

    const { result } = renderHook(() => useBulkAnalysis());
    await act(async () => {
      await result.current.upload([file()]);
    });

    expect(result.current.state.phase).toBe("error");
    const calls = status.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(status.mock.calls.length).toBe(calls);
  });

  it("surfaces an upload failure without starting a poll", async () => {
    const { APIError } = await import("@/lib/api");
    upload.mockRejectedValue(new APIError(413, "file_too_large", "Batch too large"));

    const { result } = renderHook(() => useBulkAnalysis());
    await act(async () => {
      await result.current.upload([file()]);
    });

    expect(result.current.state.phase).toBe("error");
    expect(status).not.toHaveBeenCalled();
  });

  it("rejects an empty selection before calling the API", async () => {
    const { result } = renderHook(() => useBulkAnalysis());
    await act(async () => {
      await result.current.upload([]);
    });
    expect(result.current.state.phase).toBe("error");
    expect(upload).not.toHaveBeenCalled();
  });
});
