/**
 * Security headers served with the app's own HTML.
 *
 * The API sets security headers on its JSON responses, but the browser
 * enforces these against the DOCUMENT'S origin — so none of that protected
 * the pages Vercel serves. Before `headers()` existed in next.config.js the
 * dashboard could be framed by any site (clickjack a recruiter into clicking
 * "reject" or "delete" through an invisible overlay) and there was no CSP
 * limiting where the page could load code from or send data to.
 *
 * These are asserted because a CSP regression is SILENT: delete the header
 * and every page still renders, every test still passes, and the protection
 * is simply gone. Nothing else in the suite would notice.
 */

import { describe, it, expect } from "vitest";

type Header = { key: string; value: string };

async function headersFor(env: Record<string, string | undefined>) {
  const prev = { ...process.env };
  Object.assign(process.env, env);
  // next.config.js reads process.env at module scope, so re-require it.
  const modulePath = require.resolve("../../next.config.js");
  delete require.cache[modulePath];
  const config = require("../../next.config.js");
  const result = await config.headers();
  process.env = prev;
  return result[0].headers as Header[];
}

function get(headers: Header[], key: string) {
  return headers.find((h) => h.key.toLowerCase() === key.toLowerCase())?.value;
}

describe("security headers", () => {
  it("sets a Content-Security-Policy", async () => {
    const csp = get(await headersFor({}), "Content-Security-Policy");
    expect(csp).toBeTruthy();
    expect(csp).toContain("default-src 'self'");
  });

  it("forbids framing, which is what makes clickjacking possible", async () => {
    const headers = await headersFor({});
    expect(get(headers, "Content-Security-Policy")).toContain("frame-ancestors 'none'");
    // Belt and braces for older scanners/browsers.
    expect(get(headers, "X-Frame-Options")).toBe("DENY");
  });

  it("restricts connect-src to the API and Supabase, not the whole internet", async () => {
    const csp = await headersFor({
      NEXT_PUBLIC_API_URL: "https://api.hirelens.com",
      NEXT_PUBLIC_SUPABASE_URL: "https://proj.supabase.co",
    }).then((h) => get(h, "Content-Security-Policy")!);

    expect(csp).toContain("connect-src 'self' https://api.hirelens.com https://proj.supabase.co");
    // The point of connect-src: an injected script can't phone home.
    expect(csp).not.toContain("connect-src *");
  });

  it("keeps only the API's origin, never a full URL with a path", async () => {
    // CSP source expressions are origins. Pasting a full URL in silently
    // makes the directive not match the requests it was meant to allow.
    const csp = await headersFor({
      NEXT_PUBLIC_API_URL: "https://api.hirelens.com/api/v1/",
    }).then((h) => get(h, "Content-Security-Policy")!);

    expect(csp).toContain("https://api.hirelens.com");
    expect(csp).not.toContain("https://api.hirelens.com/api");
  });

  it("falls back to a safe default when the API URL is unparseable", async () => {
    // A typo'd env var must not throw at config load, which would take the
    // whole deploy down.
    const headers = await headersFor({ NEXT_PUBLIC_API_URL: "not a url" });
    expect(get(headers, "Content-Security-Policy")).toContain("connect-src 'self'");
  });

  it("blocks plugins, base-tag hijacking and cross-origin form posts", async () => {
    const csp = get(await headersFor({}), "Content-Security-Policy")!;
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self'");
  });

  it("sets the remaining hardening headers", async () => {
    const headers = await headersFor({});
    expect(get(headers, "X-Content-Type-Options")).toBe("nosniff");
    expect(get(headers, "Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    expect(get(headers, "Strict-Transport-Security")).toContain("max-age=");
    expect(get(headers, "Cross-Origin-Opener-Policy")).toBe("same-origin");
    expect(get(headers, "Permissions-Policy")).toContain("camera=()");
  });

  it("does not advertise the framework version", async () => {
    const config = require("../../next.config.js");
    expect(config.poweredByHeader).toBe(false);
  });
});
