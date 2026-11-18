/**
 * The Content-Security-Policy, delivered as a <meta> tag in the root layout.
 *
 * The frontend is a static export, so there is no server to send it as a
 * header, and a header set per host would have to be kept in step with the
 * API address by hand. Built here, from the same NEXT_PUBLIC_* values the
 * client uses, it is always right and works on any host.
 *
 * The session token lives in browser storage, so what matters most is what an
 * injected script could do with it: connect-src lets the page talk only to
 * this site, the API and Supabase. 'unsafe-inline' stays for scripts and
 * styles because the App Router's bootstrap and the components' inline
 * styles need it without a nonce pipeline, which a static export cannot have.
 *
 * Not settable from a meta tag, so set by the host instead (public/_headers,
 * vercel.json, the Render snippet in docs/DEPLOYMENT.md): frame-ancestors,
 * the anti-clickjacking rule.
 */
function originOf(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

export function contentSecurityPolicy(env: {
  apiUrl?: string;
  supabaseUrl?: string;
}): string {
  const connect = ["'self'", originOf(env.apiUrl || "http://localhost:8000")];
  const supabase = originOf(env.supabaseUrl);
  if (supabase) connect.push(supabase, supabase.replace(/^http/, "ws"));

  return [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect.filter(Boolean).join(" ")}`,
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}
