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
    (set) => ({
      user: null,
      token: null,
      isLoading: false,
      error: null,
      requiresEmailConfirmation: false,
      hasHydrated: false,
      sessionChecked: false,
      setHasHydrated: (v) => set({ hasHydrated: v }),
      setAuth: (token, user) => set({ token, user, isLoading: false, error: null, hasHydrated: true, sessionChecked: true }),

      // Silently re-authenticates using the httpOnly session cookie set at
      // login/signup, so a page reload doesn't need the raw token to have
      // survived in localStorage. Safe to call even when there's no
      // session at all — it just resolves with the user logged out.
      restoreSession: async () => {
        try {
          const res = await authAPI.session();
          set({ token: res.access_token, user: res.user as User, sessionChecked: true });
        } catch {
          set({ token: null, user: null, sessionChecked: true });
        }
      },

      login: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const res = await authAPI.login(email, password);
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
            set({
              isLoading: false,
              requiresEmailConfirmation: true,
              user: null,
              token: null,
            });
            return { requiresEmailConfirmation: true };
          }

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
          set({ isLoading: false, error: msg, token: null, user: null });
          throw e;
        }
      },

      oauthLogin: async (accessToken) => {
        set({ isLoading: true, error: null });
        try {
          const res = await authAPI.oauthVerify(accessToken);
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
          set({ isLoading: false, error: msg, token: null, user: null });
          throw e;
        }
      },

      logout: () => {
        supabase.auth.signOut();
        authAPI.logout().catch(() => {
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
