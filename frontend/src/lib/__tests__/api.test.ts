import { describe, it, expect } from "vitest";
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
