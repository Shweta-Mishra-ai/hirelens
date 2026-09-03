/**
 * HireLens — Design Tokens
 *
 * Single source of truth for the app's visual language. Every page should
 * import from here instead of hardcoding hex values — that inconsistency
 * (multiple competing palettes across pages) was the single biggest visual
 * quality gap found in the July 2026 UI audit and is what this file fixes
 * going forward.
 *
 * Palette identity: dark slate base + indigo/violet brand accent, matching
 * the dashboard/analyze/match/teams pages, which were already the most
 * consistent and closest to a "Linear/Stripe/Vercel"-grade look. This file
 * documents that palette so every other page can be brought in line with it,
 * rather than introducing a new theme.
 */

export const color = {
  // Backgrounds
  bg: "#0B0F17",
  bgAlt: "#0F172A",
  surface: "rgba(30, 41, 59, 0.6)",
  surfaceSolid: "#1E293B",
  surfaceHover: "rgba(255, 255, 255, 0.03)",

  // Borders
  border: "rgba(255, 255, 255, 0.08)",
  borderStrong: "rgba(255, 255, 255, 0.12)",
  borderSubtle: "rgba(255, 255, 255, 0.05)",

  // Text
  textPrimary: "#F8FAFC",
  textSecondary: "#CBD5E1",
  textMuted: "#94A3B8",
  textFaint: "#64748B",

  // Brand (indigo/violet)
  brand: "#6366F1",
  brandLight: "#818CF8",
  brandDark: "#4F46E5",
  brandGlow: "rgba(99, 102, 241, 0.4)",
  violet: "#8B5CF6",

  // Semantic
  success: "#10B981",
  successBg: "rgba(16, 185, 129, 0.12)",
  successBorder: "rgba(16, 185, 129, 0.3)",

  warning: "#F59E0B",
  warningBg: "rgba(245, 158, 11, 0.12)",
  warningBorder: "rgba(245, 158, 11, 0.3)",

  danger: "#EF4444",
  dangerBg: "rgba(239, 68, 68, 0.12)",
  dangerBorder: "rgba(239, 68, 68, 0.3)",

  info: "#3B82F6",
  infoBg: "rgba(59, 130, 246, 0.1)",
  infoBorder: "rgba(59, 130, 246, 0.25)",
} as const;

export const gradient = {
  brand: `linear-gradient(135deg, ${color.brand}, ${color.violet})`,
  brandButton: `linear-gradient(135deg, ${color.brand}, ${color.brandDark})`,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 9999,
} as const;

export const font = {
  mono: "monospace",
} as const;
