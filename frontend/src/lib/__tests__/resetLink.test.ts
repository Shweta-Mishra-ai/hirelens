/**
 * Reading a password reset link.
 *
 * The one that matters most is the Supabase shape. It puts the recovery token
 * in the URL *fragment*, which never reaches the server and is invisible to
 * useSearchParams() — a page that only looks at the query string finds nothing
 * and tells the user their link is broken when it is perfectly good.
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  readResetLink,
  passwordStrength,
  captureResetLink,
  recaptureResetLink,
  __resetCaptureForTests,
} from "../resetLink";

beforeEach(() => {
  window.history.replaceState(null, "", "/reset-password#access_token=tok-from-hash&type=recovery");
});

describe("readResetLink", () => {
  it("finds the token Supabase puts in the fragment", () => {
    const link = readResetLink(
      "",
      "#access_token=abc123&expires_in=3600&refresh_token=r1&token_type=bearer&type=recovery",
    );
    expect(link.token).toBe("abc123");
    expect(link.error).toBeNull();
  });

  it("finds the token the local flow puts in the query string", () => {
    const link = readResetLink("?token=local-token-xyz", "");
    expect(link.token).toBe("local-token-xyz");
    expect(link.error).toBeNull();
  });

  it("prefers the fragment when a link somehow carries both", () => {
    const link = readResetLink("?token=from-query", "#access_token=from-fragment");
    expect(link.token).toBe("from-fragment");
  });

  it("reports an expired link rather than looking for a token", () => {
    const link = readResetLink(
      "",
      "#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired",
    );
    expect(link.token).toBeNull();
    expect(link.error).toMatch(/expired/i);
  });

  it("falls back to the provider's own wording for an error it doesn't know", () => {
    const link = readResetLink("", "#error=server_error&error_description=Something+odd+happened");
    expect(link.token).toBeNull();
    expect(link.error).toBe("Something odd happened");
  });

  it("returns nothing for a bare visit to the page", () => {
    expect(readResetLink("", "")).toEqual({ token: null, error: null });
  });

  it("treats a blank token as no token", () => {
    expect(readResetLink("?token=%20%20", "").token).toBeNull();
  });

  it("does not choke on a malformed fragment", () => {
    expect(() => readResetLink("", "#####")).not.toThrow();
    expect(readResetLink("", "#####").token).toBeNull();
  });

  it("keeps a token containing dots and dashes intact", () => {
    // A Supabase access token is a JWT.
    const jwt = "eyJhbGciOi.eyJzdWIiOi.sig-nature_123";
    expect(readResetLink("", `#access_token=${jwt}&type=recovery`).token).toBe(jwt);
  });
});

describe("passwordStrength", () => {
  it("says nothing for an empty box", () => {
    expect(passwordStrength("")).toEqual({ score: 0, label: "" });
  });

  it("rates a short password lowest", () => {
    expect(passwordStrength("abc").score).toBe(0);
  });

  it("rates a long mixed password highest", () => {
    expect(passwordStrength("Tr0ubador&Horse1").score).toBe(4);
  });

  it("climbs with length and variety", () => {
    const weak = passwordStrength("password").score;
    const better = passwordStrength("passwordpassword").score;
    const best = passwordStrength("Passw0rd!Passw0rd").score;
    expect(better).toBeGreaterThan(weak);
    expect(best).toBeGreaterThan(better);
  });

  it("never returns a score outside the styles array", () => {
    for (const p of ["a", "aaaaaaaa", "Aa1!aaaaaaaaaaaaaaaaaaaaaaaaa"]) {
      const { score } = passwordStrength(p);
      expect(score).toBeGreaterThanOrEqual(0);
      expect(score).toBeLessThanOrEqual(4);
    }
  });
});

describe("captureResetLink", () => {
  beforeEach(() => {
    __resetCaptureForTests();
  });

  it("keeps answering with the link the page arrived on", () => {
    // The page removes the token from the URL the moment it has read it, so a
    // credential is not left in the address bar. A second read of
    // window.location therefore finds nothing — and anything that re-runs
    // (a remount, an effect invoked twice) would conclude the link was empty
    // and tell someone holding a good link that it will not work.
    const first = captureResetLink();
    expect(first.token).toBe("tok-from-hash");

    window.history.replaceState(null, "", "/reset-password");
    expect(captureResetLink()).toEqual(first);
  });

  it("re-reads when a new link arrives in the same tab", () => {
    expect(captureResetLink().token).toBe("tok-from-hash");

    window.location.hash = "#access_token=second-token&type=recovery";
    expect(recaptureResetLink().token).toBe("second-token");
  });

  it("re-reading picks up an error link too", () => {
    captureResetLink();
    window.location.hash = "#error=access_denied&error_code=otp_expired";
    const next = recaptureResetLink();
    expect(next.token).toBeNull();
    expect(next.error).toMatch(/expired/i);
  });
});
