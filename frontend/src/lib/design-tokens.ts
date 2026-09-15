/**
 * HireLens — design tokens for the few call sites that need a raw value
 * (Recharts props, inline SVG, canvas) rather than a Tailwind class.
 *
 * Everything that CAN be a Tailwind class SHOULD be a Tailwind class. Reach
 * for this module only when a third-party API demands a string. The values
 * mirror tailwind.config.js and globals.css.
 */

export const color = {
  canvas: "#0A0C10",
  canvasRaised: "#10131A",
  canvasOverlay: "#161A23",
  canvasInset: "#070910",

  line: "#1E2430",
  lineStrong: "#2A3242",
  lineSubtle: "#161B24",

  content: "#E8EBF0",
  contentMuted: "#98A1B2",
  contentFaint: "#646E80",

  brand: "#5B63EF",
  brandLight: "#7D88FB",
  brandDark: "#474DD4",

  positive: "#3DD68C",
  caution: "#E8B341",
  critical: "#F2555A",
  info: "#4C9DF5",
} as const;

/**
 * Score bands. These thresholds are the single definition used by the score
 * ring, the sub-score bars, the dashboard table and the CSV export, so a
 * candidate can never be "amber" in one place and "green" in another.
 */
export const SCORE_BANDS = [
  { min: 75, key: "strong", label: "Strong", color: color.positive },
  { min: 55, key: "review", label: "Review", color: color.caution },
  { min: 0, key: "weak", label: "High risk", color: color.critical },
] as const;

export type ScoreBand = (typeof SCORE_BANDS)[number];

export function scoreBand(score: number): ScoreBand {
  const n = Number.isFinite(score) ? score : 0;
  return SCORE_BANDS.find((b) => n >= b.min) ?? SCORE_BANDS[SCORE_BANDS.length - 1];
}

export function scoreColor(score: number): string {
  return scoreBand(score).color;
}

/** Chart series colours, ordered so adjacent series stay distinguishable. */
export const CHART_SERIES = [
  color.brand,
  color.info,
  color.positive,
  color.caution,
  color.critical,
  color.brandLight,
] as const;
