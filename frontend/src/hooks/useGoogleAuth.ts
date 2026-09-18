"use client";
import { useCallback, useEffect, useState } from "react";
import { healthAPI, authAPI, APIError } from "@/lib/api";
import { supabase } from "@/lib/supabase";

/**
 * Google sign-in availability and the sign-in action.
 *
 * Google sign-in needs Supabase configured on both sides — the browser to
 * start the OAuth redirect, and the API to exchange the resulting token. The
 * previous build simply hid the button whenever the browser half was missing,
 * so the feature appeared to have been removed with no explanation. It now
 * stays visible and says what is missing.
 */
export type GoogleAuthState =
  | { status: "checking" }
  | { status: "ready" }
  | { status: "unconfigured"; reason: string };

function browserConfigured() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const placeholder = (v?: string) =>
    !v || v.includes("placeholder") || v.includes("your-project") || v.includes("your-anon");
  return !placeholder(url) && !placeholder(key);
}

export function useGoogleAuth() {
  const [state, setState] = useState<GoogleAuthState>({ status: "checking" });
  const [error, setError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    if (!browserConfigured()) {
      setState({
        status: "unconfigured",
        reason:
          "Google sign-in isn't set up for this deployment. Ask your administrator to add the Supabase keys, or sign in with your email below.",
      });
      return;
    }

    healthAPI
      .check()
      .then((h) => {
        if (cancelled) return;
        // `undefined` means an older backend that predates this flag — assume
        // it works rather than hiding a feature that may be fine.
        if (h.google_auth_ready === false) {
          setState({
            status: "unconfigured",
            reason:
              "Google sign-in isn't finished on the server side yet. Sign in with your email below.",
          });
        } else {
          setState({ status: "ready" });
        }
      })
      .catch(() => {
        // If health is unreachable the whole app is down; let the normal
        // sign-in error path report that rather than blaming Google.
        if (!cancelled) setState({ status: "ready" });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async () => {
    setError(null);
    setRedirecting(true);
    try {
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: `${window.location.origin}/dashboard` },
      });
      if (oauthError) {
        setError(oauthError.message || "Google sign-in could not be started.");
        setRedirecting(false);
      }
      // On success the browser navigates away, so nothing to reset.
    } catch {
      setError("Google sign-in could not be started. Try your email and password instead.");
      setRedirecting(false);
    }
  }, []);

  return { state, signIn, error, redirecting, clearError: () => setError(null) };
}

/**
 * Completes the OAuth round trip.
 *
 * Supabase redirects back to /dashboard with the token in the URL *fragment*.
 * It must be exchanged for a HireLens session and then stripped from the URL,
 * so a refresh or a copied link doesn't carry a credential.
 */
export async function consumeOAuthFragment(): Promise<
  { ok: true; token: string; user: unknown } | { ok: false; error: string } | null
> {
  if (typeof window === "undefined") return null;

  const hash = window.location.hash;
  if (!hash || !hash.includes("access_token")) {
    // Supabase reports OAuth failures as query params, not a fragment.
    const params = new URLSearchParams(window.location.search);
    const err = params.get("error_description") || params.get("error");
    if (err) {
      window.history.replaceState(null, "", window.location.pathname);
      return { ok: false, error: decodeURIComponent(err.replace(/\+/g, " ")) };
    }
    return null;
  }

  const accessToken = new URLSearchParams(hash.slice(1)).get("access_token");
  window.history.replaceState(null, "", window.location.pathname);
  if (!accessToken) return { ok: false, error: "Google sign-in returned no token." };

  try {
    const res = await authAPI.oauthVerify(accessToken);
    return { ok: true, token: res.access_token, user: res.user };
  } catch (e) {
    return {
      ok: false,
      error:
        e instanceof APIError
          ? e.message
          : "Google sign-in could not be verified. Sign in with your email instead.",
    };
  }
}
