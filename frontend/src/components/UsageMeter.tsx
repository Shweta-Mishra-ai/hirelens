"use client";
import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";
import { billingAPI, USAGE_CHANGED_EVENT, type PlanUsage } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/cn";

const PLAN_LABEL: Record<PlanUsage["plan"], string> = {
  free: "Free plan",
  pro: "Pro plan",
  team: "Team plan",
};

/**
 * This month's analyses against the plan's allowance, in the sidebar.
 *
 * Renders nothing when the plan is unlimited and there is no upgrade link —
 * the default for a deployment that has not configured quotas — and nothing
 * if the usage request fails: the meter is a convenience, and an error in the
 * chrome on every page would be worse than its absence. The server still
 * enforces the quota either way.
 */
export function UsageMeter({ collapsed }: { collapsed: boolean }) {
  const token = useAuthStore((s) => s.token);
  const pathname = usePathname();
  const [usage, setUsage] = useState<PlanUsage | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setUsage(await billingAPI.usage(token));
    } catch {
      setUsage(null);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load, pathname]);

  useEffect(() => {
    const refresh = () => void load();
    window.addEventListener(USAGE_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(USAGE_CHANGED_EVENT, refresh);
  }, [load]);

  if (!usage || collapsed) return null;
  if (usage.unlimited && !usage.upgrade_url) return null;

  const limit = usage.limit ?? 0;
  const consumed = usage.used + usage.in_progress;
  const pct = limit ? Math.min(100, Math.round((consumed / limit) * 100)) : 0;
  const exhausted = !usage.unlimited && (usage.remaining ?? 0) === 0;
  const low = !usage.unlimited && !exhausted && pct >= 80;
  const resets = new Date(usage.period_end).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

  return (
    <div className="mx-2 mb-2 rounded-lg border border-line-subtle bg-canvas-inset/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-content">{PLAN_LABEL[usage.plan]}</span>
        {!usage.unlimited && (
          <span
            className={cn(
              "text-2xs tabular-nums",
              exhausted ? "text-critical" : low ? "text-caution" : "text-content-faint",
            )}
          >
            {consumed}/{limit}
          </span>
        )}
      </div>

      {!usage.unlimited && (
        <>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-canvas-overlay"
            role="progressbar"
            aria-label="Analyses used this month"
            aria-valuemin={0}
            aria-valuemax={limit}
            aria-valuenow={consumed}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width]",
                exhausted ? "bg-critical" : low ? "bg-caution" : "bg-brand-500",
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-1.5 text-2xs text-content-faint">
            {exhausted
              ? `All analyses used. Resets ${resets}.`
              : `${usage.remaining} left this month · resets ${resets}`}
          </p>
        </>
      )}

      {usage.upgrade_url && usage.plan !== "team" && (
        <a
          href={usage.upgrade_url}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "mt-2.5 flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
            "focus-visible:outline-none focus-visible:shadow-focus",
            exhausted || low
              ? "bg-brand-500 text-white hover:bg-brand-600"
              : "border border-line-strong text-content-muted hover:bg-canvas-overlay hover:text-content",
          )}
        >
          <Sparkles aria-hidden className="size-3.5" />
          Upgrade
        </a>
      )}
    </div>
  );
}
