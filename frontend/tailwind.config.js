/** @type {import('tailwindcss').Config} */

/**
 * HireLens — Tailwind theme.
 *
 * This file is the SINGLE source of truth for the app's visual language.
 * It previously competed with two other palettes (a navy/blue set here, a
 * "Slate Obsidian" set in globals.css, and a third in lib/design-tokens.ts),
 * which is why the UI looked inconsistent from page to page. The CSS
 * variables in globals.css and the tokens in lib/design-tokens.ts are now
 * both derived from these values rather than redefining them.
 */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Canvas — deep neutral slate, no blue cast
        canvas: {
          DEFAULT: "#0A0C10", // page background
          raised: "#10131A", // cards sitting on the page
          overlay: "#161A23", // modals, popovers, hover surfaces
          inset: "#070910", // wells, code blocks, inputs
        },
        line: {
          DEFAULT: "#1E2430", // default border
          strong: "#2A3242", // emphasised border / dividers
          subtle: "#161B24", // hairlines inside cards
        },
        content: {
          DEFAULT: "#E8EBF0", // primary text
          muted: "#98A1B2", // secondary text
          faint: "#646E80", // tertiary / captions
          inverse: "#0A0C10", // text on solid brand fills
        },
        brand: {
          50: "#EEF1FF",
          100: "#E0E5FF",
          200: "#C6CEFF",
          300: "#A3AEFF",
          400: "#7D88FB",
          500: "#5B63EF", // primary action
          600: "#474DD4",
          700: "#3A3FAC",
          800: "#2F3488",
          900: "#22265E",
        },
        // Semantic — used for verdicts and score bands. Deliberately
        // desaturated vs. the old pure #10B981/#EF4444 so a report full of
        // status colour doesn't read like a traffic light.
        positive: {
          DEFAULT: "#3DD68C",
          soft: "rgba(61, 214, 140, 0.12)",
          line: "rgba(61, 214, 140, 0.28)",
        },
        caution: {
          DEFAULT: "#E8B341",
          soft: "rgba(232, 179, 65, 0.12)",
          line: "rgba(232, 179, 65, 0.28)",
        },
        critical: {
          DEFAULT: "#F2555A",
          soft: "rgba(242, 85, 90, 0.12)",
          line: "rgba(242, 85, 90, 0.28)",
        },
        info: {
          DEFAULT: "#4C9DF5",
          soft: "rgba(76, 157, 245, 0.12)",
          line: "rgba(76, 157, 245, 0.28)",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        // Tighter, more deliberate scale than Tailwind's default
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.5rem" }],
        lg: ["1rem", { lineHeight: "1.625rem" }],
        xl: ["1.125rem", { lineHeight: "1.75rem", letterSpacing: "-0.01em" }],
        "2xl": ["1.375rem", { lineHeight: "1.875rem", letterSpacing: "-0.015em" }],
        "3xl": ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.02em" }],
        "4xl": ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.025em" }],
        "5xl": ["3rem", { lineHeight: "3.25rem", letterSpacing: "-0.03em" }],
      },
      borderRadius: {
        sm: "0.375rem",
        DEFAULT: "0.5rem",
        md: "0.625rem",
        lg: "0.75rem",
        xl: "1rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        // Dark-UI shadows need a ring of light, not just a drop shadow
        card: "0 1px 2px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.04)",
        raised: "0 4px 16px -4px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05)",
        popover: "0 16px 40px -12px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.07)",
        focus: "0 0 0 3px rgba(91, 99, 239, 0.35)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "bar-grow": {
          from: { transform: "scaleX(0)" },
          to: { transform: "scaleX(1)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) both",
        shimmer: "shimmer 1.6s infinite",
        "bar-grow": "bar-grow 0.6s cubic-bezier(0.16, 1, 0.3, 1) both",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};
