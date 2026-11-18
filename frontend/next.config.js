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
// treated as an error. Each host announces its own builds: Vercel with
// VERCEL_ENV, Netlify with CONTEXT, Cloudflare Pages with CF_PAGES, Render
// with RENDER.
const isRealDeployment =
  process.env.VERCEL_ENV === "production" ||
  process.env.VERCEL_ENV === "preview" ||
  process.env.CONTEXT === "production" ||
  process.env.CONTEXT === "deploy-preview" ||
  process.env.CONTEXT === "branch-deploy" ||
  process.env.CF_PAGES === "1" ||
  process.env.RENDER === "true";

if (isRealDeployment) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  const looksLocal = !apiUrl || /localhost|127\.0\.0\.1/.test(apiUrl);
  if (looksLocal) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is " +
        (apiUrl ? `"${apiUrl}"` : "not set") +
        ", so this build would call the visitor's own machine for every " +
        "request and nothing would work except the pages themselves.\n\n" +
        "Set it in the hosting project's environment variables to the API's " +
        "public URL — the one Render prints as \"Available at your primary " +
        "URL\", e.g. https://hirelens-api.onrender.com — then redeploy.\n\n" +
        "The API's ALLOWED_ORIGINS must list this site's origin in return, or " +
        "the browser blocks the requests before they are sent.",
    );
  }
}

// ── Static export ────────────────────────────────────────────────────────────
//
// The app is entirely client-side — every page fetches from the API in the
// browser — so it is built as plain files (`out/`) that any static host can
// serve: Netlify, Cloudflare Pages or Render's static sites, all free and all
// allowing commercial use. No Node server runs in production.
//
// What a static build cannot do, and where it went instead:
//   • dynamic routes  → a report is /report/?id=…, see src/lib/routes.ts;
//   • response headers → public/_headers (Netlify, Cloudflare Pages),
//     vercel.json and render.yaml carry the same set;
//   • Content-Security-Policy → a <meta> tag built in src/lib/csp.ts, so it
//     holds on any host. frame-ancestors cannot be set by a meta tag, so the
//     anti-framing rule lives in the header files above.
//
// trailingSlash: every page is written as <route>/index.html, the one layout
// every static host serves without per-host rewrite rules.

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  reactStrictMode: true,
  // No "X-Powered-By: Next.js" advertising the framework and its version
  // (only matters for `next dev`, the export has no server).
  poweredByHeader: false,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
};

module.exports = nextConfig;
