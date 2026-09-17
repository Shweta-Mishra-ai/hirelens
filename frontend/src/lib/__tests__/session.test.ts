/**
 * When a 401 ends a session, and when it does not.
 *
 * Every page used to sign the user out on any 401, which makes the session
 * only as durable as the least reliable response in the app — one bad answer
 * from a cold start, a half-finished deploy or a proxy serving its own error
 * page, and a recruiter is thrown back to sign-in mid-task.
 */
import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";
import { APIError } from "../api";
import { tokenExpiresAt, isTokenExpired, classifyAuthFailure, signInUrl } from "../session";
import * as api from "../api";

function jwt(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256" })}.${b64(claims)}.signature`;
}

const future = () => jwt({ sub: "u1", exp: Math.floor(Date.now() / 1000) + 3600 });
const past = () => jwt({ sub: "u1", exp: Math.floor(Date.now() / 1000) - 3600 });

describe("reading a token's expiry", () => {
  it("reads exp from the payload", () => {
    const exp = Math.floor(Date.now() / 1000) + 60;
    expect(tokenExpiresAt(jwt({ exp }))).toBe(exp);
  });

  it("treats an unreadable token as undecided, not expired", () => {
    // An opaque token is the server's business. Guessing "expired" here would
    // sign someone out over a token shape this code simply does not parse.
    expect(tokenExpiresAt("not-a-jwt")).toBeNull();
    expect(isTokenExpired("not-a-jwt")).toBe(false);
    expect(isTokenExpired(jwt({ sub: "u1" }))).toBe(false);
  });

  it("handles null and empty", () => {
    expect(tokenExpiresAt(null)).toBeNull();
    expect(isTokenExpired(null)).toBe(false);
  });

  it("knows a live token from a dead one", () => {
    expect(isTokenExpired(future())).toBe(false);
    expect(isTokenExpired(past())).toBe(true);
  });

  it("allows a little clock skew", () => {
    const justNow = jwt({ exp: Math.floor(Date.now() / 1000) - 5 });
    expect(isTokenExpired(justNow)).toBe(false);
  });
});

describe("classifying a failed request", () => {
  let me: MockInstance<typeof api.authAPI.me>;
  beforeEach(() => { me = vi.spyOn(api.authAPI, "me"); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("ignores errors that are not 401", async () => {
    expect(await classifyAuthFailure(new APIError(500, "x", "boom"), future())).toBe("not-auth");
    expect(await classifyAuthFailure(new APIError(404, "x", "gone"), future())).toBe("not-auth");
    expect(await classifyAuthFailure(new Error("plain"), future())).toBe("not-auth");
    expect(me).not.toHaveBeenCalled();
  });

  it("does not end the session when the identity endpoint still accepts the token", async () => {
    // This is the whole point: a 401 from one endpoint, while the session is
    // demonstrably fine, must not sign anyone out.
    me.mockResolvedValue({ id: "u1", email: "a@b.com" });
    expect(await classifyAuthFailure(new APIError(401, "unauthorized", "no"), future())).toBe("transient");
  });

  it("ends the session when the identity endpoint refuses it too", async () => {
    me.mockRejectedValue(new APIError(401, "unauthorized", "no"));
    expect(await classifyAuthFailure(new APIError(401, "unauthorized", "no"), future())).toBe("expired");
  });

  it("keeps the session when the check itself cannot be made", async () => {
    // Unreachable API, timeout, 5xx — no answer, so no verdict. Signing out
    // here would turn every outage into a forced sign-out for every user.
    me.mockRejectedValue(new APIError(0, "network_error", "unreachable"));
    expect(await classifyAuthFailure(new APIError(401, "unauthorized", "no"), future())).toBe("transient");

    me.mockRejectedValue(new APIError(503, "unavailable", "down"));
    expect(await classifyAuthFailure(new APIError(401, "unauthorized", "no"), future())).toBe("transient");
  });

  it("does not bother checking a token that has already expired", async () => {
    expect(await classifyAuthFailure(new APIError(401, "unauthorized", "no"), past())).toBe("expired");
    expect(me).not.toHaveBeenCalled();
  });

  it("treats a missing token as expired", async () => {
    expect(await classifyAuthFailure(new APIError(401, "unauthorized", "no"), null)).toBe("expired");
    expect(me).not.toHaveBeenCalled();
  });
});

describe("signInUrl", () => {
  it("carries the reason, so the sign-in page can explain itself", () => {
    expect(signInUrl()).toBe("/login?session=expired");
  });
});
