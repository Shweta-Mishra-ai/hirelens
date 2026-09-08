/**
 * HireLens — Auth Store (Zustand + persist)
 * Fixed:
 * - signup handles requires_email_confirmation response
 * - Token expiry detection
 * - isLoading always reset (even on error)
 * - Security: the raw JWT is no longer persisted to localStorage (see
 *   restoreSession below) — only non-sensitive user display info is.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { authAPI, APIError } from "@/lib/api";
import type { User } from "@/types";
import { supabase } from "@/lib/supabase";

/**
 * Per-tab token stash — the fallback for browsers that drop the httpOnly
 * session cookie.
 *
 * The cookie is the primary session-restore mechanism, but in the default
 * deployment (Vercel frontend + Render API) it is a *third-party* cookie:
 * `*.vercel.app` and `*.onrender.com` are separate registrable sites. Safari
 * (ITP), Firefox strict mode, and Chrome Incognito all block third-party
 * cookies by default, so on those browsers `/auth/session` finds nothing and
 * the user is bounced to /login on every single page refresh.
 *
 * sessionStorage — deliberately NOT localStorage — closes that hole:
 *   - it survives a refresh and in-tab navigation, which is the actual break;
 *   - it is scoped to one tab and cleared when that tab closes, so a token
 *     does not linger on disk indefinitely the way the old localStorage
 *     persistence did;
 *   - it is never the sole proof of a session: the stashed token is
 *     re-validated against /auth/me before it is trusted (see restoreSession),
 *     so a stale or tampered value logs the user out rather than half-in.
 *
 * This is a mitigation, not the fix. Serving the frontend and API from one
 * registrable domain makes the cookie first-party and makes this dead code.
 */
const TOKEN_STASH_KEY = "hirelens-token";

function stashToken(token: string | null) {
  try {
    if (typeof window === "undefined") return;
    if (token) window.sessionStorage.setItem(TOKEN_STASH_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_STASH_KEY);
  } catch {
    // Private mode / storage disabled — the cookie path still works, and
    // worst case the user logs in again. Never let this throw into a caller.
  }
}

function readStashedToken(): string | null {
  try {
    if (typeof window === "undefined") return null;
    return window.sessionStorage.getItem(TOKEN_STASH_KEY);
  } catch {
    return null;
  }
}

interface AuthStore {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
  requiresEmailConfirmation: boolean;
  hasHydrated: boolean;
  // True once a session-restore attempt (success OR failure) has
  // completed. Pages should gate their "redirect to /login if not
  // authenticated" logic on this, not on hasHydrated — token is no
  // longer in localStorage, so right after hydration there's a brief
  // window where restoreSession() is still in flight.
  sessionChecked: boolean;
  setHasHydrated: (v: boolean) => void;
  setAuth: (token: string | null, user: User | null) => void;
  restoreSession: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    email: string,
    password: string,
    fullName: string,
    company?: string,
  ) => Promise<{ requiresEmailConfirmation: boolean }>;
  oauthLogin: (accessToken: string) => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isLoading: false,
      error: null,
      requiresEmailConfirmation: false,
      hasHydrated: false,
      sessionChecked: false,
      setHasHydrated: (v) => set({ hasHydrated: v }),
      setAuth: (token, user) => {
        stashToken(token);
        set({ token, user, isLoading: false, error: null, hasHydrated: true, sessionChecked: true });
      },

      // Silently re-authenticates on page load, so a reload doesn't need the
      // raw token to have survived in localStorage. Safe to call even when
      // there's no session at all — it just resolves with the user logged out.
      //
      // Two paths, in order of preference:
      //   1. The httpOnly session cookie (/auth/session). Preferred: the
      //      token never touches JavaScript-readable storage at all.
      //   2. The per-tab sessionStorage stash, re-validated against
      //      /auth/me. Only reached when the browser dropped the cookie —
      //      see the TOKEN_STASH_KEY comment above for why that happens on
      //      Safari/Firefox/Incognito in the cross-site deployment.
      restoreSession: async () => {
        try {
          const res = await authAPI.session();
          stashToken(res.access_token);
          set({ token: res.access_token, user: res.user as User, sessionChecked: true });
          return;
        } catch {
          // Fall through to the stash — no session cookie reached us.
        }

        const stashed = readStashedToken();
        if (stashed) {
          try {
            // Never trust the stash on its own: a token that is expired,
            // revoked, or tampered with must log the user out, not leave
            // the app in a half-authenticated state where every subsequent
            // call 401s.
            const me = await authAPI.me(stashed);
            const persisted = get().user;
            set({
              token: stashed,
              user: {
                ...(persisted ?? {}),
                id: me.id,
                email: me.email,
              } as User,
              sessionChecked: true,
            });
            return;
          } catch {
            stashToken(null);
          }
        }

        set({ token: null, user: null, sessionChecked: true });
      },

      login: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const res = await authAPI.login(email, password);
          stashToken(res.access_token);
          set({
            token: res.access_token,
            user: res.user as User,
            isLoading: false,
            error: null,
            sessionChecked: true,
          });
        } catch (e) {
          const msg =
            e instanceof APIError ? e.message : "Login failed. Please try again.";
          stashToken(null);
          set({ isLoading: false, error: msg, token: null, user: null });
          throw e;
        }
      },

      signup: async (email, password, fullName, company) => {
        set({ isLoading: true, error: null });
        try {
          const res = await authAPI.signup({
            email,
            password,
            full_name: fullName,
            company,
          });

          // Handle email confirmation required case
          if ((res as any).requires_email_confirmation) {
            stashToken(null);
            set({
              isLoading: false,
              requiresEmailConfirmation: true,
              user: null,
              token: null,
            });
            return { requiresEmailConfirmation: true };
          }

          stashToken(res.access_token);
          set({
            token: res.access_token,
            user: res.user as User,
            isLoading: false,
            requiresEmailConfirmation: false,
            error: null,
            sessionChecked: true,
          });
          return { requiresEmailConfirmation: false };
        } catch (e) {
          const msg =
            e instanceof APIError ? e.message : "Signup failed. Please try again.";
          stashToken(null);
          set({ isLoading: false, error: msg, token: null, user: null });
          throw e;
        }
      },

      oauthLogin: async (accessToken) => {
        set({ isLoading: true, error: null });
        try {
          const res = await authAPI.oauthVerify(accessToken);
          stashToken(res.access_token);
          set({
            token: res.access_token,
            user: res.user,
            isLoading: false,
            error: null,
            sessionChecked: true,
          });
        } catch (e) {
          const msg =
            e instanceof APIError ? e.message : "Google Sign-In verification failed.";
          stashToken(null);
          set({ isLoading: false, error: msg, token: null, user: null });
          throw e;
        }
      },

      logout: () => {
        // Capture the token BEFORE clearing local state — it is what the
        // backend needs in order to revoke the session rather than just
        // forget it locally.
        const token = get().token;
        stashToken(null);
        supabase.auth.signOut();
        authAPI.logout(token ?? undefined).catch(() => {
          // Best-effort — if this fails the cookie just expires on its own
          // (7-day max-age); local state is cleared regardless below.
        });
        set({
          user: null,
          token: null,
          error: null,
          requiresEmailConfirmation: false,
          sessionChecked: true,
        });
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: "hirelens-auth-v3", // bumped version — v2 persisted the raw token; this one deliberately doesn't
      // Only non-sensitive display info is persisted now. The token lives
      // in memory only for the current page session, restored on load via
      // the httpOnly cookie (see restoreSession) rather than read back out
      // of localStorage.
      partialize: (s) => ({ user: s.user }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
        state?.restoreSession();
      },
    },
  ),
);
