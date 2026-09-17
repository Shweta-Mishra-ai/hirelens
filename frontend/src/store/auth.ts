/**
 * HireLens — Auth Store (Zustand + persist)
 *
 * The session, persisted across reloads.
 *
 * Sign-up handles the confirmation-required answer as its own outcome rather
 * than an error, and `isLoading` is reset on every path out — including the
 * failing ones, which is what keeps a failed sign-in from leaving a spinner on
 * screen.
 *
 * Nothing here decides that a session has ended. That judgement lives in
 * lib/session.ts, which checks with the identity endpoint before a 401 is
 * allowed to sign anyone out.
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
  setHasHydrated: (v: boolean) => void;
  setAuth: (token: string | null, user: User | null) => void;
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
      setHasHydrated: (v) => set({ hasHydrated: v }),
      setAuth: (token, user) => set({ token, user, isLoading: false, error: null, hasHydrated: true }),

      login: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const res = await authAPI.login(email, password);
          set({
            token: res.access_token,
            user: res.user as User,
            isLoading: false,
            error: null,
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
          });
        } catch (e) {
          const msg =
            e instanceof APIError ? e.message : "Google Sign-In verification failed.";
          set({ isLoading: false, error: msg, token: null, user: null });
          throw e;
        }
      },

      logout: () => {
        // Best effort. This client holds no session of its own (see
        // lib/supabase.ts), so there is usually nothing to revoke — but a
        // rejected promise here must never stop the local session being
        // cleared, which is the part that actually signs the user out.
        void supabase.auth.signOut().catch(() => {});
        set({
          user: null,
          token: null,
          error: null,
          requiresEmailConfirmation: false,
        });
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: "hirelens-auth-v2", // bumped version clears old stale storage
      partialize: (s) => ({ user: s.user, token: s.token }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);
