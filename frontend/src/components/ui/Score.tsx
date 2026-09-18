"use client";
import { scoreBand, scoreColor } from "@/lib/design-tokens";
import { cn } from "@/lib/cn";

/**
 * The headline credibility score. Rendered as an arc rather than a bare
 * numeral so the value reads against its range at a glance.
 */
export function ScoreRing({
  score,
  size = 116,
  label = "Credibility",
  className,
}: {
  score: number;
  size?: number;
  label?: string;
  className?: string;
}) {
  const safe = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  const band = scoreBand(safe);
  const stroke = size >= 100 ? 8 : 6;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  // 270° sweep, leaving a gap at the bottom for the label.
  const sweep = 0.75;
  const dash = c * sweep;

  return (
    <div className={cn("relative inline-flex flex-col items-center", className)}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`${label} score ${safe} out of 100 — ${band.label}`}
        className="-rotate-[225deg]"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          className="text-line-strong"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={band.color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash * (safe / 100)} ${c}`}
          style={{ transition: "stroke-dasharray 0.7s cubic-bezier(0.16,1,0.3,1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="tabular font-semibold leading-none"
          style={{ fontSize: size * 0.3, color: band.color }}
        >
          {safe}
        </span>
        <span className="mt-1 text-2xs font-medium uppercase tracking-wider text-content-faint">
          {label}
        </span>
      </div>
    </div>
  );
}

/**
 * A single sub-score row. The label, bar and value sit on one baseline so a
 * column of six can be scanned vertically — the previous layout split the
 * label and number to opposite edges with the bar on its own line.
 */
export function ScoreBar({
  label,
  score,
  rationale,
  className,
}: {
  label: string;
  score: number;
  /** The model's explanation, shown beneath rather than hidden in a tooltip. */
  rationale?: string;
  className?: string;
}) {
  const safe = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  return (
    <div className={cn("py-3", className)}>
      <div className="flex items-center gap-3">
        <span className="w-40 shrink-0 truncate text-sm text-content-muted">{label}</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas-inset">
          <div
            className="h-full origin-left rounded-full animate-bar-grow"
            style={{ width: `${safe}%`, background: scoreColor(safe) }}
          />
        </div>
        <span className="w-8 shrink-0 text-right text-sm font-medium tabular" style={{ color: scoreColor(safe) }}>
          {safe}
        </span>
      </div>
      {rationale && (
        <p className="ml-[calc(10rem+0.75rem)] mt-1.5 text-xs leading-relaxed text-content-faint">
          {rationale}
        </p>
      )}
    </div>
  );
}

/** Compact inline score for table rows and list items. */
export function ScorePill({ score }: { score: number }) {
  const safe = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  const band = scoreBand(safe);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-sm font-medium tabular"
      style={{ color: band.color, borderColor: `${band.color}40`, background: `${band.color}14` }}
    >
      {safe}
    </span>
  );
}
