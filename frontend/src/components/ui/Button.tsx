"use client";
import { forwardRef } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "link";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  // A disabled primary must read as inert, not as "nearly enabled". A
  // translucent brand fill still looks like the main call to action, which
  // invites clicks that do nothing; dropping to the neutral surface makes the
  // unavailable state unambiguous at a glance.
  primary:
    "bg-brand-500 text-white hover:bg-brand-400 active:bg-brand-600 " +
    "shadow-[0_1px_0_rgba(255,255,255,0.12)_inset] " +
    "disabled:bg-canvas-overlay disabled:text-content-faint disabled:shadow-none " +
    "disabled:border disabled:border-line",
  secondary:
    "bg-canvas-overlay text-content border border-line-strong hover:bg-canvas-overlay/70 " +
    "hover:border-line-strong/80 active:bg-canvas-inset disabled:text-content-faint",
  ghost:
    "text-content-muted hover:text-content hover:bg-canvas-overlay disabled:text-content-faint",
  danger:
    "bg-critical/12 text-critical border border-critical-line hover:bg-critical/20 " +
    "active:bg-critical/25 disabled:opacity-50",
  link: "text-brand-400 hover:text-brand-300 underline-offset-4 hover:underline p-0 h-auto",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-md",
  md: "h-9 px-3.5 text-sm gap-2 rounded-md",
  lg: "h-11 px-5 text-base gap-2 rounded-lg",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /** Rendered before the label. Omitted while `loading`, which shows a spinner. */
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
  fullWidth?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, iconRight, fullWidth, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      // A loading button stays focusable but must not fire twice.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center font-medium whitespace-nowrap",
        "transition-colors duration-150 ease-out",
        "disabled:cursor-not-allowed",
        "focus-visible:outline-none focus-visible:shadow-focus",
        variant !== "link" && SIZES[size],
        VARIANTS[variant],
        fullWidth && "w-full",
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 aria-hidden className="size-4 animate-spin" />
      ) : (
        icon && <span aria-hidden className="inline-flex shrink-0">{icon}</span>
      )}
      {children}
      {iconRight && !loading && <span aria-hidden className="inline-flex shrink-0">{iconRight}</span>}
    </button>
  );
});
