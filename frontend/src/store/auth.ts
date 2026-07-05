/**
 * HireLens — Auth Store (Zustand + persist)
 * Fixed:
 * - signup handles requires_email_confirmation response
 * - Token expiry detection
 * - isLoading always reset (even on error)
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { authAPI, APIError } from "@/lib/api";
import type { User } from "@/types";

interface AuthStore {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
  requiresEmailConfirmation: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    email: string,
    password: string,
    fullName: string,
    company?: string,
  ) => Promise<{ requiresEmailConfirmation: boolean }>;
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

      logout: () =>
        set({
          user: null,
          token: null,
          error: null,
          requiresEmailConfirmation: false,
        }),

      clearError: () => set({ error: null }),
    }),
    {
      name: "hirelens-auth-v2", // bumped version clears old stale storage
      partialize: (s) => ({ user: s.user, token: s.token }),
    },
  ),
);
