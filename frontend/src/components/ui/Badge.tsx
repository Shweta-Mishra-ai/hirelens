import { cn } from "@/lib/cn";

type Tone = "neutral" | "brand" | "positive" | "caution" | "critical" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-canvas-overlay text-content-muted border-line-strong",
  brand: "bg-brand-500/12 text-brand-300 border-brand-500/30",
  positive: "bg-positive-soft text-positive border-positive-line",
  caution: "bg-caution-soft text-caution border-caution-line",
  critical: "bg-critical-soft text-critical border-critical-line",
  info: "bg-info-soft text-info border-info-line",
};

export function Badge({
  tone = "neutral",
  dot,
  icon,
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLSpanElement> & {
  tone?: Tone;
  /** Small leading status dot — use for live/verdict states, not decoration. */
  dot?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5",
        "text-2xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {icon && <span aria-hidden className="inline-flex">{icon}</span>}
      {children}
    </span>
  );
}
