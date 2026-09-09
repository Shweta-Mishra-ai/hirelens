/**
 * HireLens — Shared UI Primitives ("The Verification Desk")
 *
 * Rebuilt to match the new design system in design-tokens.ts: flat ink
 * surfaces with a hairline border instead of blurred glass panels, a single
 * petrol-teal accent instead of an indigo/violet gradient, restrained
 * radius, and no colored glow shadows. See design-tokens.ts for the full
 * design rationale.
 */
import { CSSProperties, ReactNode, ButtonHTMLAttributes, InputHTMLAttributes } from "react";
import { color, radius, shadow } from "@/lib/design-tokens";

// ── Card ─────────────────────────────────────────────────────────────────────
export function Card({
  children,
  style,
  raised = false,
}: {
  children: ReactNode;
  style?: CSSProperties;
  /** Use for genuinely floating elements (menus/modals) — adds a soft neutral shadow instead of just a border. */
  raised?: boolean;
}) {
  return (
    <div
      style={{
        background: color.surface,
        border: `1px solid ${color.border}`,
        borderRadius: radius.lg,
        boxShadow: raised ? shadow.raised : "none",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ── Badge ────────────────────────────────────────────────────────────────────
type BadgeTone = "success" | "warning" | "danger" | "info" | "neutral";

const BADGE_TONES: Record<BadgeTone, { bg: string; border: string; fg: string }> = {
  success: { bg: color.successBg, border: color.successBorder, fg: color.success },
  warning: { bg: color.warningBg, border: color.warningBorder, fg: color.warning },
  danger: { bg: color.dangerBg, border: color.dangerBorder, fg: color.danger },
  info: { bg: color.infoBg, border: color.infoBorder, fg: color.info },
  neutral: { bg: color.surfaceRaised, border: color.border, fg: color.textSecondary },
};

export function Badge({
  children,
  tone = "neutral",
  dot = false,
  icon,
  title,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  /** Small status dot, for "live"/"active" indicators — solid, not a pulsing glow. */
  dot?: boolean;
  /** Leading icon, as an alternative to `dot` when the state needs more than a colour. */
  icon?: ReactNode;
  /** Native tooltip — used to carry the detail behind a short status label. */
  title?: string;
}) {
  const t = BADGE_TONES[tone];
  return (
    <span
      title={title}
      style={{
        padding: "4px 10px",
        borderRadius: radius.sm,
        background: t.bg,
        border: `1px solid ${t.border}`,
        color: t.fg,
        fontSize: 12,
        fontWeight: 600,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: title ? "help" : undefined,
      }}
    >
      {dot && (
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: t.fg }} />
      )}
      {icon && <span style={{ display: "inline-flex", flexShrink: 0 }}>{icon}</span>}
      {children}
    </span>
  );
}

// ── Button ───────────────────────────────────────────────────────────────────
type ButtonVariant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "primary",
  children,
  style,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const base: CSSProperties = {
    borderRadius: radius.md,
    fontWeight: 600,
    fontSize: 13,
    cursor: rest.disabled ? "default" : "pointer",
    opacity: rest.disabled ? 0.45 : 1,
    padding: "10px 18px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    transition: "background-color 0.12s ease, border-color 0.12s ease",
  };

  const variants: Record<ButtonVariant, CSSProperties> = {
    primary: {
      background: color.brand,
      color: "#F5F5F2",
      border: `1px solid ${color.brand}`,
    },
    secondary: {
      background: "transparent",
      color: color.textSecondary,
      border: `1px solid ${color.borderStrong}`,
    },
    ghost: {
      background: "transparent",
      color: color.textMuted,
      border: "1px solid transparent",
    },
  };

  return (
    <button style={{ ...base, ...variants[variant], ...style }} {...rest}>
      {children}
    </button>
  );
}

// ── Input ────────────────────────────────────────────────────────────────────
export function TextInput({ style, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      style={{
        width: "100%",
        boxSizing: "border-box",
        padding: "10px 13px",
        background: color.bgAlt,
        border: `1px solid ${color.border}`,
        borderRadius: radius.md,
        color: color.textPrimary,
        fontSize: 13,
        outline: "none",
        ...style,
      }}
      {...rest}
    />
  );
}

// ── Field label (pairs with TextInput) ──────────────────────────────────────
export function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <label
      style={{
        display: "block",
        fontSize: 12,
        fontWeight: 600,
        color: color.textSecondary,
        marginBottom: 6,
      }}
    >
      {children}
    </label>
  );
}

// ── Stat card (dashboard hero metrics) ──────────────────────────────────────
export function StatCard({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: ReactNode;
  icon: ReactNode;
  tone: BadgeTone;
}) {
  const t = BADGE_TONES[tone];
  return (
    <Card style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: color.textMuted }}>
          {label}
        </span>
        <span style={{ display: "flex", alignItems: "center", color: t.fg }}>{icon}</span>
      </div>
      <div
        style={{
          fontSize: 30,
          fontWeight: 600,
          color: color.textPrimary,
          fontFamily: "var(--font-mono), monospace",
          letterSpacing: -0.5,
        }}
      >
        {value}
      </div>
    </Card>
  );
}

// ── Page shell (full-height dark background wrapper) ───────────────────────
export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", background: color.bg, color: color.textPrimary }}>
      {children}
    </div>
  );
}

// ── Alert banner (error/info messages in forms) ─────────────────────────────
export function AlertBanner({
  children,
  tone = "danger",
  icon,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  icon?: ReactNode;
}) {
  const t = BADGE_TONES[tone];
  return (
    <div
      style={{
        padding: "11px 14px",
        borderRadius: radius.md,
        background: t.bg,
        border: `1px solid ${t.border}`,
        color: t.fg,
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      {icon && <span style={{ flexShrink: 0 }}>{icon}</span>}
      <span>{children}</span>
    </div>
  );
}
