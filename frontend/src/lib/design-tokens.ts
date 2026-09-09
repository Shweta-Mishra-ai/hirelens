/**
 * HireLens — Design Tokens ("The Verification Desk")
 *
 * Design plan (see /mnt/skills/public/frontend-design for the process this
 * followed): the previous system — near-black canvas, bright indigo/violet
 * gradient, glassmorphic blurred cards, colored glow shadows, uniform 16–24px
 * radius, uppercase pill labels — is the generic "AI-generated dark SaaS"
 * look almost by definition. It reads as a demo because it *is* the default
 * treatment for "make me a dashboard," not a choice made for this product.
 *
 * HireLens's actual subject is verification and evidence — recruiters
 * deciding whether to trust a resume. That points somewhere more like an
 * audit ledger than a startup pitch deck: flat ink surfaces, hairline rules
 * instead of blur-and-glow, restrained radius, a single deliberate accent
 * (a petrol teal — verification/seal-adjacent, and not the indigo-violet
 * every AI tool defaults to), and real typographic hierarchy carrying the
 * personality instead of decoration.
 *
 * Color: ink (#12141A), surface (#191B22), line (#2A2D37), paper-toned text
 * (#EDEDEA / warm off-white, not cool #F8FAFC), petrol-teal accent (#3B7D78).
 * Type: Fraunces (serif, headings — set via --font-display) carries the
 * personality; IBM Plex Sans (--font-body) is quiet UI text; IBM Plex Mono
 * (--font-mono) is used ONLY for real data values (scores, ids, timestamps).
 * Layout: flat surfaces + hairline borders, no blur, no glow shadows —
 * elevation comes from a single soft neutral shadow used sparingly.
 */

export const color = {
  // Backgrounds — flat, no transparency/blur layering
  bg: "#12141A",
  bgAlt: "#0E0F13",
  surface: "#191B22",
  surfaceSolid: "#191B22",
  surfaceRaised: "#1F222B",
  surfaceHover: "#20232C",

  // Borders — hairline rules, not glows
  border: "#2A2D37",
  borderStrong: "#383C48",
  borderSubtle: "#22242D",

  // Text — warm off-white (ledger paper on dark ink), not cool white
  textPrimary: "#EDEDEA",
  textSecondary: "#B4B4AC",
  textMuted: "#8A8B82",
  textFaint: "#5F6058",

  // Brand — deep petrol teal (verification/seal), deliberately not
  // indigo/violet/blue
  brand: "#3B7D78",
  // Foreground for text/icons sitting ON the brand fill. Off-white rather
  // than pure white, matching the paper-toned text elsewhere.
  onBrand: "#F5F5F2",
  brandLight: "#5FA39D",
  brandDark: "#2A5D59",
  brandGlow: "rgba(59, 125, 120, 0.35)", // kept only for focus rings, never decorative glow
  violet: "#3B7D78", // legacy alias — same as brand, no separate violet accent anymore

  // Semantic — muted/desaturated rather than saturated "AI dashboard" hues
  success: "#5C9A6C",
  successBg: "rgba(92, 154, 108, 0.14)",
  successBorder: "rgba(92, 154, 108, 0.35)",

  warning: "#B98A3E",
  warningBg: "rgba(185, 138, 62, 0.14)",
  warningBorder: "rgba(185, 138, 62, 0.35)",

  danger: "#B3543A",
  dangerBg: "rgba(179, 84, 58, 0.14)",
  dangerBorder: "rgba(179, 84, 58, 0.35)",

  info: "#5B84A6",
  infoBg: "rgba(91, 132, 166, 0.14)",
  infoBorder: "rgba(91, 132, 166, 0.35)",
} as const;

// No decorative gradients — a flat brand fill stands in for what used to be
// a gradient button/glow. Kept as an export so existing call sites don't all
// need touching at once; new code should just use color.brand directly.
export const gradient = {
  brand: color.brand,
  brandButton: color.brand,
} as const;

export const radius = {
  sm: 4,
  md: 6,
  lg: 8,
  xl: 10,
  pill: 9999,
} as const;

export const font = {
  display: "var(--font-display)",
  body: "var(--font-body)",
  mono: "var(--font-mono)",
} as const;

// Single restrained elevation shadow — neutral (no color tint), used only
// where something genuinely floats above the page (menus, modals). Cards
// on the page surface use a hairline border instead, never a shadow.
export const shadow = {
  raised: "0 4px 16px -4px rgba(0, 0, 0, 0.45)",
} as const;
