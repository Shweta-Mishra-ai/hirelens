/** @type {import('next').NextConfig} */

// The API sets security headers on its own JSON responses, but that does
// nothing for the HTML and JavaScript Vercel serves — and the browser only
// enforces these against the document's own origin. Without them the
// dashboard could be framed by any site (clickjacking a recruiter into
// clicking "reject" or "delete" through an invisible overlay), and there was
// no CSP at all limiting where the page may load code from or connect to.
const apiOrigin = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").origin;
  } catch {
    return "http://localhost:8000";
  }
})();

const supabaseOrigin = (() => {
  try {
    return process.env.NEXT_PUBLIC_SUPABASE_URL
      ? new URL(process.env.NEXT_PUBLIC_SUPABASE_URL).origin
      : "";
  } catch {
    return "";
  }
})();

// connect-src is built from the origins this app actually talks to, so a
// script that did get injected cannot exfiltrate to an attacker's server.
const connectSrc = ["'self'", apiOrigin, supabaseOrigin].filter(Boolean).join(" ");

const csp = [
  "default-src 'self'",
  // 'unsafe-inline' for styles is required: this app styles everything with
  // React inline `style` props rather than classes, and every one of those
  // is an inline style from the browser's point of view. Removing it means
  // migrating the whole UI off inline styles first.
  "style-src 'self' 'unsafe-inline'",
  // Next.js's App Router bootstraps with inline scripts and, in dev, uses
  // eval for fast refresh. 'unsafe-eval' is dev-only so production keeps the
  // stronger policy.
  process.env.NODE_ENV === "development"
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  // Fonts are self-hosted via @fontsource, so no external font origin is
  // needed at all.
  "font-src 'self' data:",
  `connect-src ${connectSrc}`,
  // Nothing in this app should ever be framed, or frame anything.
  "frame-ancestors 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  // Stops a hijacked <form> from POSTing credentials to another origin.
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  // frame-ancestors above is the modern control; X-Frame-Options is kept for
  // browsers and scanners that still look for it.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // This app asks for none of these; denying them means a compromised
  // dependency cannot silently start using them either.
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
  },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  // Isolates this page's browsing-context group from anything that opens it,
  // so a window.opener reference can't reach back into it.
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig = {
  reactStrictMode: true,
  // Don't advertise the framework version to scanners.
  poweredByHeader: false,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

module.exports = nextConfig;
