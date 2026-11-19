import { describe, expect, it } from "vitest";
import { legacyReportId, reportHref } from "@/lib/routes";
import { contentSecurityPolicy } from "@/lib/csp";

describe("report links", () => {
  it("carry the id in the query string, where a static page can read it", () => {
    expect(reportHref("3f2a")).toBe("/report?id=3f2a");
  });

  it("encode ids that are not URL-safe", () => {
    expect(reportHref("a b&c=d")).toBe("/report?id=a%20b%26c%3Dd");
  });
});

describe("content security policy", () => {
  it("lets the page reach only itself, the API and Supabase", () => {
    const csp = contentSecurityPolicy({
      apiUrl: "https://api.example.com/some/path",
      supabaseUrl: "https://abc.supabase.co",
    });
    const connect = csp.split("; ").find((d) => d.startsWith("connect-src"));
    expect(connect).toBe(
      "connect-src 'self' https://api.example.com https://abc.supabase.co wss://abc.supabase.co",
    );
  });

  it("falls back to the local API when none is configured", () => {
    expect(contentSecurityPolicy({})).toContain("connect-src 'self' http://localhost:8000");
  });

  it("ignores a malformed Supabase URL instead of emitting a broken policy", () => {
    const csp = contentSecurityPolicy({ apiUrl: "https://api.example.com", supabaseUrl: "not a url" });
    expect(csp).toContain("connect-src 'self' https://api.example.com;");
  });

  it("leaves frame-ancestors to the host, because a meta tag cannot set it", () => {
    // Browsers ignore frame-ancestors in a <meta> policy and log a warning.
    expect(contentSecurityPolicy({})).not.toContain("frame-ancestors");
  });

  it("refuses plugins and foreign form targets", () => {
    const csp = contentSecurityPolicy({});
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("form-action 'self'");
    expect(csp).toContain("base-uri 'self'");
  });
});

describe("old /report/<id> links", () => {
  const id = "3f2a9c1e-7b4d-4e8a-9c1f-0a2b3c4d5e6f";

  it("are recognised with or without a trailing slash", () => {
    expect(legacyReportId(`/report/${id}`)).toBe(id);
    expect(legacyReportId(`/report/${id}/`)).toBe(id);
  });

  it("never match the report page's own files", () => {
    // Matching these broke navigation: the router's request for
    // /report/index.txt was redirected to a report called "index.txt".
    for (const path of ["/report/index.txt", "/report/index.html", "/report/__next.report.__PAGE__.txt", "/report/", "/report"]) {
      expect(legacyReportId(path)).toBeNull();
    }
  });

  it("ignore anything that is not a report id", () => {
    expect(legacyReportId("/report/not-a-uuid")).toBeNull();
    expect(legacyReportId(`/reports/${id}`)).toBeNull();
    expect(legacyReportId(`/report/${id}/extra`)).toBeNull();
  });
});
