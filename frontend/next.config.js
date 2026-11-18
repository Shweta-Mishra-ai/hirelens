// ── Refuse to ship a build that cannot reach its own API ────────────────────
//
// NEXT_PUBLIC_* values are inlined at build time. If NEXT_PUBLIC_API_URL is
// missing, the client falls back to http://localhost:8000 — the *visitor's*
// machine. The site then loads perfectly, because it is static, and every
// single request fails: sign-in, sign-up, the dashboard, all of it. The build
// goes green and nothing anywhere says a word.
//
// Only a real deployment is checked. CI builds with a localhost API on
// purpose, and so does anyone running `npm run build` locally, so neither is
// treated as an error.
const isRealDeployment =
  process.env.VERCEL_ENV === "production" || process.env.VERCEL_ENV === "preview";

if (isRealDeployment) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  const looksLocal = !apiUrl || /localhost|127\.0\.0\.1/.test(apiUrl);
  if (looksLocal) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is " +
        (apiUrl ? `"${apiUrl}"` : "not set") +
        ", so this build would call the visitor's own machine for every " +
        "request and nothing would work except the pages themselves.\n\n" +
        "Set it in the Vercel project's Environment Variables to the API's " +
        "public URL — the one Render prints as \"Available at your primary " +
        "URL\", e.g. https://hirelens-gjoe.onrender.com — then redeploy.\n\n" +
        "The API's ALLOWED_ORIGINS must list this site's origin in return, or " +
        "the browser blocks the requests before they are sent.",
    );
  }
}

// ── Security headers ─────────────────────────────────────────────────────────
//
// The session token is kept in browser storage, so the thing that matters
// most is limiting what an injected script could do with it: the CSP below
// only lets the page talk to this site, the API and Supabase, and refuses to
// be framed (clickjacking). 'unsafe-inline' remains for scripts and styles
// because the App Router's bootstrap and the components' inline styles need
// it without a nonce pipeline; everything else is closed.
//
// Production builds only: the dev server relies on eval() for hot reload.
function originOf(url) {
  try {
    return url ? new URL(url).origin : null;
  } catch {
    return null;
  }
}

function securityHeaders() {
  const connect = ["'self'", originOf(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")];
  const supabase = originOf(process.env.NEXT_PUBLIC_SUPABASE_URL);
  if (supabase) connect.push(supabase, supabase.replace(/^http/, "ws"));

  const csp = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect.filter(Boolean).join(" ")}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");

  return [
    { key: "Content-Security-Policy", value: csp },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
    { key: "Strict-Transport-Security", value: "max-age=31536000" },
  ];
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No "X-Powered-By: Next.js" advertising the framework and its version.
  poweredByHeader: false,
  async headers() {
    if (process.env.NODE_ENV !== "production") return [];
    return [{ source: "/:path*", headers: securityHeaders() }];
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
};

module.exports = nextConfig;
