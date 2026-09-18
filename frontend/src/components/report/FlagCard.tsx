"use client";
import { useState } from "react";
import { AlertTriangle, ChevronDown, Lightbulb } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { EvidenceQuote } from "./Evidence";
import { cn } from "@/lib/cn";
import type { Flag } from "@/types";

const SEVERITY: Record<
  string,
  { label: string; tone: "critical" | "caution" | "info"; border: string }
> = {
  high: { label: "High", tone: "critical", border: "border-l-critical" },
  medium: { label: "Medium", tone: "caution", border: "border-l-caution" },
  low: { label: "Low", tone: "info", border: "border-l-info" },
};

export function FlagCard({ flag, defaultOpen = false }: { flag: Flag; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const sev = SEVERITY[flag.severity] ?? SEVERITY.low;

  return (
    <div className={cn("rounded-lg border border-line border-l-2 bg-canvas-raised", sev.border)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:bg-canvas-overlay"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={sev.tone}>{sev.label}</Badge>
            <Badge tone="neutral" className="capitalize">
              {flag.category.replace(/_/g, " ")}
            </Badge>
          </div>
          <h3 className="mt-2 text-sm font-medium text-content">{flag.title}</h3>
          {!open && (
            <p className="mt-1 line-clamp-1 text-xs text-content-faint">{flag.description}</p>
          )}
        </div>
        <ChevronDown
          aria-hidden
          className={cn(
            "mt-0.5 size-4 shrink-0 text-content-faint transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="space-y-3 border-t border-line-subtle px-4 py-3.5">
          <p className="text-sm leading-relaxed text-content-muted">{flag.description}</p>

          {flag.evidence && <EvidenceQuote>{flag.evidence}</EvidenceQuote>}

          {flag.action && (
            <div className="flex items-start gap-2.5 rounded-lg border border-brand-500/25 bg-brand-500/[0.06] px-3.5 py-2.5">
              <Lightbulb aria-hidden className="mt-0.5 size-3.5 shrink-0 text-brand-400" />
              <div>
                <div className="text-2xs font-medium uppercase tracking-wider text-brand-400">
                  Suggested next step
                </div>
                <p className="mt-0.5 text-sm leading-relaxed text-content-muted">{flag.action}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function FlagSummary({ flags }: { flags: Flag[] }) {
  const counts = flags.reduce<Record<string, number>>((acc, f) => {
    acc[f.severity] = (acc[f.severity] ?? 0) + 1;
    return acc;
  }, {});

  if (flags.length === 0) {
    return (
      <p className="text-sm text-content-muted">
        No concerns were raised. That means nothing in the text contradicted itself —
        it is not confirmation that the claims are true.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <AlertTriangle aria-hidden className="size-4 text-content-faint" />
      {(["high", "medium", "low"] as const).map((s) =>
        counts[s] ? (
          <Badge key={s} tone={SEVERITY[s].tone}>
            {counts[s]} {SEVERITY[s].label.toLowerCase()}
          </Badge>
        ) : null,
      )}
    </div>
  );
}
