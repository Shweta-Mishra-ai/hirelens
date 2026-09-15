import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  relativeTime,
  absoluteTime,
  initials,
  pluralize,
  truncate,
  formatBytes,
} from "@/lib/format";

/**
 * `relativeTime` exists because the dashboard rendered the literal string
 * "NaNd ago" for every report whose `created_at` was missing — the in-memory
 * storage path never set one, and the old formatter did
 * `Math.floor((Date.now() - new Date("").getTime()) / 60000)` without
 * checking the result.
 */
describe("relativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-15T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("never renders NaN for a missing or unparseable timestamp", () => {
    for (const bad of ["", null, undefined, "not a date", "0000", "undefined"]) {
      const out = relativeTime(bad as string | null | undefined);
      expect(out).not.toContain("NaN");
      expect(out).not.toContain("Invalid");
      expect(out).toBe("—");
    }
  });

  it("formats recent timestamps", () => {
    expect(relativeTime("2026-06-15T11:59:30Z")).toBe("just now");
    expect(relativeTime("2026-06-15T11:45:00Z")).toBe("15m ago");
    expect(relativeTime("2026-06-15T09:00:00Z")).toBe("3h ago");
    expect(relativeTime("2026-06-13T12:00:00Z")).toBe("2d ago");
  });

  it("switches to an absolute date beyond a month", () => {
    const out = relativeTime("2026-01-02T12:00:00Z");
    expect(out).not.toMatch(/ago/);
    expect(out).toMatch(/2026/);
  });

  it("treats a future timestamp as 'just now' rather than negative time", () => {
    // Client and server clocks drift; "-3m ago" is never the right output.
    expect(relativeTime("2026-06-15T12:05:00Z")).toBe("just now");
  });
});

describe("absoluteTime", () => {
  it("returns an empty string for unusable input rather than 'Invalid Date'", () => {
    expect(absoluteTime("")).toBe("");
    expect(absoluteTime(null)).toBe("");
    expect(absoluteTime("nonsense")).toBe("");
  });

  it("formats a real timestamp", () => {
    expect(absoluteTime("2026-06-15T12:00:00Z")).toMatch(/2026/);
  });
});

describe("initials", () => {
  it("derives initials from names and emails", () => {
    expect(initials("Priya Raghavan")).toBe("PR");
    expect(initials("priya.raghavan@gmail.com")).toBe("PR");
    expect(initials("Cher")).toBe("CH");
  });

  it("degrades safely on empty input", () => {
    expect(initials("")).toBe("?");
    expect(initials(null)).toBe("?");
    expect(initials("   ")).toBe("?");
  });
});

describe("pluralize", () => {
  it("agrees with the count", () => {
    expect(pluralize(1, "report")).toBe("1 report");
    expect(pluralize(0, "report")).toBe("0 reports");
    expect(pluralize(3, "report")).toBe("3 reports");
  });

  it("accepts an irregular plural", () => {
    expect(pluralize(2, "person", "people")).toBe("2 people");
  });
});

describe("truncate", () => {
  it("leaves short strings alone", () => {
    expect(truncate("short", 20)).toBe("short");
  });

  it("breaks on a word boundary", () => {
    const out = truncate("the quick brown fox jumps over", 20);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(21);
    expect(out).not.toContain("  ");
  });
});

describe("formatBytes", () => {
  it("formats sizes a person would recognise", () => {
    expect(formatBytes(512)).toBe("1 KB");
    expect(formatBytes(1024 * 500)).toBe("500 KB");
    expect(formatBytes(1024 * 1024 * 2.5)).toBe("2.5 MB");
  });

  it("degrades safely on nonsense input", () => {
    expect(formatBytes(0)).toBe("0 KB");
    expect(formatBytes(-5)).toBe("0 KB");
    expect(formatBytes(NaN)).toBe("0 KB");
  });
});
