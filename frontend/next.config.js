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

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
};

module.exports = nextConfig;
