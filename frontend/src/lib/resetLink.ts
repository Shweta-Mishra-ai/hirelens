/**
 * Reading the token out of a password reset link.
 *
 * There are two shapes, because there are two senders:
 *
 *   Supabase  /reset-password#access_token=...&type=recovery
 *   Local     /reset-password?token=...
 *
 * Supabase puts its token in the URL *fragment*, not the query string. That is
 * deliberate on their part — a fragment is never sent to a server, so the
 * recovery token cannot leak into access logs or a Referer header — and it is
 * why `useSearchParams()` alone will never find it.
 *
 * A link can also arrive already refused, with `error` and `error_description`
 * in the fragment (an expired link, most often). That is a real outcome and
 * has to be shown, not treated as "no token".
 */

export interface ResetLink {
  token: string | null;
  /** A message from the sender explaining why this link will not work. */
  error: string | null;
}

function parseParams(raw: string): URLSearchParams {
  return new URLSearchParams(raw.replace(/^[#?]/, ""));
}

const FRIENDLY_ERRORS: Record<string, string> = {
  otp_expired:
    "This reset link has expired. Request a new one and use it within the hour.",
  access_denied:
    "This reset link is no longer valid. It may have expired, or already been used.",
};

/**
 * @param search window.location.search
 * @param hash   window.location.hash
 */
export function readResetLink(search: string, hash: string): ResetLink {
  const fragment = parseParams(hash);
  const query = parseParams(search);

  // An explicit refusal wins over anything else in the link.
  const errorCode = fragment.get("error_code") ?? query.get("error_code");
  const errorDescription =
    fragment.get("error_description") ?? query.get("error_description");
  const error = fragment.get("error") ?? query.get("error");

  if (error || errorCode || errorDescription) {
    const friendly = errorCode ? FRIENDLY_ERRORS[errorCode] : undefined;
    return {
      token: null,
      error:
        friendly ??
        // Supabase sends these with `+` for spaces.
        (errorDescription ? errorDescription.replace(/\+/g, " ") : null) ??
        "This reset link is not valid. Request a new one.",
    };
  }

  const token =
    fragment.get("access_token") ??
    query.get("access_token") ??
    query.get("token") ??
    fragment.get("token");

  return { token: token && token.trim() ? token.trim() : null, error: null };
}

/**
 * How strong the password is, as something to show rather than to enforce —
 * the rules that actually decide are the API's and the identity provider's.
 */
export function passwordStrength(password: string): {
  score: 0 | 1 | 2 | 3 | 4;
  label: string;
} {
  if (!password) return { score: 0, label: "" };

  let score = 0;
  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++;
  if (/\d/.test(password) && /[^A-Za-z0-9]/.test(password)) score++;

  const labels = ["Too short", "Weak", "Fair", "Good", "Strong"] as const;
  const clamped = Math.min(score, 4) as 0 | 1 | 2 | 3 | 4;
  return { score: clamped, label: labels[clamped] };
}
