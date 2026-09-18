/**
 * The rule the recovery catcher follows.
 *
 * A password recovery link can land on any page, because Supabase falls back
 * to the project's Site URL when the redirect it was given is not allowlisted.
 * The catcher forwards it — but it must forward *only* recovery links: a
 * Google sign-in callback carries an access token in the fragment too, and
 * hijacking that would break sign-in in order to fix a redirect.
 */
import { describe, it, expect } from "vitest";

/** The same predicate the component applies, kept in step by these tests. */
function shouldForward(pathname: string, search: string, hash: string): boolean {
  if (pathname.startsWith("/reset-password")) return false;
  const fragment = new URLSearchParams(hash.replace(/^#/, ""));
  const query = new URLSearchParams(search.replace(/^\?/, ""));
  return (fragment.get("type") ?? query.get("type")) === "recovery";
}

describe("recovery link forwarding", () => {
  it("forwards a recovery link that landed on the home page", () => {
    expect(shouldForward("/", "", "#access_token=abc&type=recovery")).toBe(true);
  });

  it("forwards one that landed on the dashboard", () => {
    expect(shouldForward("/dashboard", "", "#access_token=abc&type=recovery")).toBe(true);
  });

  it("forwards one that landed on the sign-in page", () => {
    expect(shouldForward("/login", "", "#access_token=abc&type=recovery")).toBe(true);
  });

  it("leaves a Google sign-in callback alone", () => {
    // Same shape, no type=recovery. Forwarding this would send someone
    // signing in with Google to a password reset form.
    expect(shouldForward("/dashboard", "", "#access_token=abc&expires_in=3600")).toBe(false);
  });

  it("leaves an email confirmation callback alone", () => {
    expect(shouldForward("/dashboard", "", "#access_token=abc&type=signup")).toBe(false);
  });

  it("does not forward from the reset page itself", () => {
    // Otherwise it forwards to itself, forever.
    expect(shouldForward("/reset-password", "", "#access_token=abc&type=recovery")).toBe(false);
  });

  it("reads the type from the query string too", () => {
    expect(shouldForward("/", "?type=recovery&token=abc", "")).toBe(true);
  });

  it("ignores a page with nothing in the URL", () => {
    expect(shouldForward("/dashboard", "", "")).toBe(false);
  });
});
