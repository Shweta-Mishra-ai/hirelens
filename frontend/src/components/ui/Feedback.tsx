"use client";
import { AlertTriangle, CheckCircle2, Info, XCircle, X } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "info" | "success" | "warning" | "error";

const TONE_STYLES: Record<Tone, { wrap: string; icon: React.ReactNode }> = {
  info: { wrap: "border-info-line bg-info-soft text-info", icon: <Info className="size-4" /> },
  success: { wrap: "border-positive-line bg-positive-soft text-positive", icon: <CheckCircle2 className="size-4" /> },
  warning: { wrap: "border-caution-line bg-caution-soft text-caution", icon: <AlertTriangle className="size-4" /> },
  error: { wrap: "border-critical-line bg-critical-soft text-critical", icon: <XCircle className="size-4" /> },
};

export function Alert({
  tone = "info",
  title,
  onDismiss,
  className,
  children,
}: {
  tone?: Tone;
  title?: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
  children?: React.ReactNode;
}) {
  const t = TONE_STYLES[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-lg border px-3.5 py-3 text-sm", t.wrap, className)}
    >
      <span aria-hidden className="mt-0.5 shrink-0">{t.icon}</span>
      <div className="min-w-0 flex-1">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className={cn("text-content-muted", title && "mt-0.5")}>{children}</div>}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="-m-1 shrink-0 rounded p-1 text-current opacity-60 transition-opacity hover:opacity-100"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      {icon && (
        <div
          aria-hidden
          className="mb-4 flex size-11 items-center justify-center rounded-xl border border-line bg-canvas-overlay text-content-faint"
        >
          {icon}
        </div>
      )}
      <h3 className="text-sm font-semibold text-content">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-content-faint">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "relative overflow-hidden rounded-md bg-canvas-overlay",
        "after:absolute after:inset-0 after:-translate-x-full after:animate-shimmer",
        "after:bg-gradient-to-r after:from-transparent after:via-white/[0.04] after:to-transparent",
        className,
      )}
    />
  );
}

/**
 * Screen-reader-only text. Used for table captions and icon-only controls
 * where a visible label would add noise.
 */
export function SrOnly({ children }: { children: React.ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
