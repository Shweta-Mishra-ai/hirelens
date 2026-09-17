/**
 * When a 401 really means the session is over.
 *
 * Every page used to call logout() the moment any request came back 401, which
 * makes the session only as durable as the least reliable response in the app.
 * One 401 from a cold start, a half-finished deploy, a proxy serving its own
 * error, or a single endpoint misbehaving, and the recruiter is thrown back to
 * the sign-in page mid-task with their work abandoned.
 *
 * A session is ended here only when the identity endpoint itself refuses the
 * token. Anything else is reported as the error it was.
 */
import { authAPI, APIError } from "@/lib/api";

/** Seconds of clock skew tolerated before a token counts as expired. */
const SKEW_SECONDS = 30;

/**
 * The token's expiry, read from the JWT payload, or null when it cannot be
 * read. The signature is NOT verified — that is the server's job, and nothing
 * here grants access. This only avoids sending a request that is certain to
 * fail, and lets the UI say "your session ended" instead of showing a generic
 * failure.
 */
export function tokenExpiresAt(token: string | null | undefined): number | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    const claims = JSON.parse(atob(padded)) as { exp?: unknown };
    return typeof claims.exp === "number" ? claims.exp : null;
  } catch {
    // An opaque token is not an expired one — let the server decide.
    return null;
  }
}

export function isTokenExpired(token: string | null | undefined): boolean {
  const exp = tokenExpiresAt(token);
  if (exp === null) return false;
  return exp * 1000 <= Date.now() - SKEW_SECONDS * 1000;
}

export type AuthFailure = "expired" | "transient" | "not-auth";

/**
 * Decide what a failed request means for the session.
 *
 *   "not-auth"   — nothing to do with authentication; show the error.
 *   "expired"    — the token is genuinely dead; end the session.
 *   "transient"  — a 401 the identity endpoint disagrees with, or one that
 *                  could not be checked because the API was unreachable.
 *                  The session stands.
 */
export async function classifyAuthFailure(
  error: unknown,
  token: string | null,
): Promise<AuthFailure> {
  if (!(error instanceof APIError) || error.status !== 401) return "not-auth";
  if (!token || isTokenExpired(token)) return "expired";

  try {
    await authAPI.me(token);
    // The token still identifies someone. Whatever produced that 401, it was
    // not the session.
    return "transient";
  } catch (check) {
    if (check instanceof APIError && check.status === 401) return "expired";
    // Unreachable, timed out, 5xx — no answer either way, so keep the session.
    return "transient";
  }
}

/** Where to send someone whose session has genuinely ended. */
export function signInUrl(reason: "expired" = "expired"): string {
  return `/login?session=${reason}`;
}
