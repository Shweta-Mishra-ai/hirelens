import { afterEach, describe, expect, it } from "vitest";
import { APIError, toAPIError } from "@/lib/api";

/**
 * Error-mapping tests.
 *
 * The case that motivated these: FastAPI returns request-validation failures
 * as `{detail: [{loc, msg, type}]}`, with no `message` key. The old mapper
 * read `body["message"]` unconditionally, so every validation failure reached
 * the user as the literal string "Server error 422" — signing up with an
 * address the server rejected gave no indication of which field was wrong.
 */
describe("toAPIError", () => {
  it("uses the app's own error envelope when present", () => {
    const err = toAPIError(409, {
      error: "conflict",
      message: "An account with this email already exists.",
      request_id: "req_abc",
    });
    expect(err).toBeInstanceOf(APIError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("conflict");
    expect(err.message).toBe("An account with this email already exists.");
    expect(err.requestId).toBe("req_abc");
  });

  it("renders a FastAPI validation error as a readable field message", () => {
    const err = toAPIError(422, {
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address",
        },
      ],
    });
    expect(err.code).toBe("validation_error");
    expect(err.message).toBe("Email: value is not a valid email address");
    expect(err.message).not.toContain("Server error");
  });

  it("names the field even when the message is nested deeper", () => {
    const err = toAPIError(422, {
      detail: [{ loc: ["body", "full_name"], msg: "Field required" }],
    });
    expect(err.message).toBe("Full name: Field required");
  });

  it("strips Pydantic's 'Value error,' prefix", () => {
    const err = toAPIError(422, {
      detail: [
        { loc: ["body", "password"], msg: "Value error, Password must be at least 8 characters." },
      ],
    });
    expect(err.message).toBe("Password: Password must be at least 8 characters.");
  });

  it("joins multiple validation failures", () => {
    const err = toAPIError(422, {
      detail: [
        { loc: ["body", "email"], msg: "Field required" },
        { loc: ["body", "password"], msg: "Field required" },
      ],
    });
    expect(err.message).toContain("Email: Field required");
    expect(err.message).toContain("Password: Field required");
  });

  it("handles a validation entry with no field location", () => {
    const err = toAPIError(422, { detail: [{ loc: ["body"], msg: "Invalid payload" }] });
    expect(err.message).toBe("Invalid payload");
  });

  it("handles FastAPI's plain-string detail", () => {
    const err = toAPIError(404, { detail: "Report not found" });
    expect(err.message).toBe("Report not found");
  });

  it("falls back to actionable copy rather than a status code", () => {
    // Every branch below used to produce "Server error <n>".
    expect(toAPIError(500, {}).message).toBe("Something went wrong on our end. Please try again.");
    expect(toAPIError(401, {}).message).toBe("Your session has expired. Please sign in again.");
    expect(toAPIError(403, {}).message).toBe("You do not have access to this.");
    expect(toAPIError(413, {}).message).toBe("That file is too large.");
    expect(toAPIError(415, {}).message).toContain("PDF or DOCX");
    expect(toAPIError(429, {}).message).toContain("Too many requests");
  });

  it("never surfaces a raw status code to the user", () => {
    for (const status of [400, 401, 404, 409, 413, 415, 422, 429, 500, 503]) {
      expect(toAPIError(status, {}).message).not.toMatch(/Server error/);
      expect(toAPIError(status, {}).message).not.toMatch(new RegExp(`\\b${status}\\b`));
    }
  });

  it("survives a non-object body", () => {
    expect(() => toAPIError(500, "gateway timeout")).not.toThrow();
    expect(() => toAPIError(500, null)).not.toThrow();
    expect(() => toAPIError(500, undefined)).not.toThrow();
  });

  it("ignores a malformed detail array instead of throwing", () => {
    const err = toAPIError(422, { detail: [null, 42, { nope: true }] });
    expect(err.message).toBeTruthy();
    expect(() => err.message).not.toThrow();
  });
});

/**
 * Response shape guards.
 *
 * These exist because a wrong shape used to reach a render and throw, and
 * React unmounts the entire tree when that happens — one bad field replaced
 * the whole dashboard, navigation included, with a generic crash page.
 * Coercing at the boundary turns that into "no rows".
 */
describe("response shape coercion", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function mockJson(body: unknown) {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      })) as typeof fetch;
  }

  it("turns a non-array reports field into an empty list", async () => {
    const { reportsAPI } = await import("@/lib/api");
    mockJson({ reports: { oops: true }, total: 1, page: 1, pages: 1 });
    const res = await reportsAPI.list("token");
    expect(Array.isArray(res.reports)).toBe(true);
    expect(res.reports).toEqual([]);
  });

  it("keeps a valid reports list intact", async () => {
    const { reportsAPI } = await import("@/lib/api");
    const row = {
      id: "r1",
      file_name: "cv.pdf",
      candidate_name: "Priya",
      overall_score: 74,
      recommendation: "manual_review",
      created_at: "2026-01-01T00:00:00Z",
      recruiter_decision: null,
    };
    mockJson({ reports: [row], total: 1, page: 1, pages: 1 });
    const res = await reportsAPI.list("token");
    expect(res.reports).toHaveLength(1);
    expect(res.total).toBe(1);
  });

  it("replaces non-numeric counts with numbers", async () => {
    const { reportsAPI } = await import("@/lib/api");
    mockJson({ reports: [], total: "many", page: null, pages: undefined });
    const res = await reportsAPI.list("token");
    expect(typeof res.total).toBe("number");
    expect(typeof res.page).toBe("number");
    expect(typeof res.pages).toBe("number");
  });

  it("normalises a malformed analytics payload", async () => {
    const { reportsAPI } = await import("@/lib/api");
    mockJson({ distribution: "nope", top_skills: 42, total_candidates: "many" });
    const res = await reportsAPI.analytics("token");
    expect(res.total_candidates).toBe(0);
    expect(Array.isArray(res.top_skills)).toBe(true);
    expect(res.distribution).toEqual({ recommended: 0, manual_review: 0, high_risk: 0 });
  });

  it("survives a completely empty body", async () => {
    const { reportsAPI } = await import("@/lib/api");
    mockJson({});
    const list = await reportsAPI.list("token");
    const analytics = await reportsAPI.analytics("token");
    expect(list.reports).toEqual([]);
    expect(analytics.distribution.recommended).toBe(0);
  });
});

describe("report shape coercion", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function mockGet(body: unknown) {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      })) as typeof fetch;
  }

  it("passes a well-formed report through", async () => {
    mockGet({
      candidate: { name: "Anita Rao" },
      skills: { all_claimed: ["python"] },
      flags: [{ severity: "medium" }],
      credibility: { overall: 74, recommendation: "manual_review" },
      summary: "Solid.",
    });
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok");
    expect(report.candidate.name).toBe("Anita Rao");
    expect(report.flags).toHaveLength(1);
    expect(report.credibility.overall).toBe(74);
  });

  it("turns a wrongly-typed list into an empty one rather than throwing on .map", async () => {
    mockGet({ flags: "critical", experience: "seven years", interview_questions: { a: 1 } });
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok");
    expect(report.flags).toEqual([]);
    expect(report.experience).toEqual([]);
    expect(report.interview_questions).toEqual([]);
    expect(() => report.flags.map((f) => f)).not.toThrow();
  });

  it("does not explode a string into one entry per character", async () => {
    mockGet({ certifications: "AWS" });
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok");
    expect(report.certifications).toEqual([]);
  });

  it("turns a wrongly-typed object into an empty one", async () => {
    mockGet({ candidate: "not an object", skills: ["python"], credibility: 5 });
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok");
    expect(report.candidate).toEqual({});
    expect(report.skills).toEqual({});
    expect(report.credibility.overall).toBe(0);
  });

  it("replaces a non-numeric score with zero", async () => {
    mockGet({ credibility: { overall: "seventy", recommendation: "manual_review" } });
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok");
    expect(report.credibility.overall).toBe(0);
    expect(report.credibility.recommendation).toBe("manual_review");
  });

  it("survives a body that is not a report at all", async () => {
    mockGet(null);
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok");
    expect(report.candidate).toEqual({});
    expect(report.flags).toEqual([]);
    expect(report.summary).toBe("");
  });

  it("keeps fields it does not know about", async () => {
    mockGet({ candidate: "bad", some_future_field: { a: 1 }, id: "r1" });
    const { reportsAPI } = await import("@/lib/api");
    const report = await reportsAPI.get("r1", "tok") as unknown as Record<string, unknown>;
    expect(report.some_future_field).toEqual({ a: 1 });
    expect(report.id).toBe("r1");
  });
});
