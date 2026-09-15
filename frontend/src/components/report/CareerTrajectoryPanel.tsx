"use client";
import { Info, TrendingUp } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import type { CareerTrajectory } from "@/types";

function Metric({
  label,
  value,
  unit,
  help,
}: {
  label: string;
  value: string | number;
  unit?: string;
  help: string;
}) {
  return (
    <div className="rounded-lg border border-line-subtle bg-canvas-inset p-3.5">
      <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
        {label}
      </div>
      <div className="mt-1.5 flex items-baseline gap-1">
        <span className="text-xl font-semibold tabular text-content">{value}</span>
        {unit && <span className="text-xs text-content-faint">{unit}</span>}
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-content-faint">{help}</p>
    </div>
  );
}

/**
 * Career trajectory.
 *
 * The version this replaces displayed a "Growth Velocity Index" that was
 * computed as `60 + roleCount*5 + skillCount*2`, clamped to 98 — so almost
 * every candidate with a normal skills list was shown as "98/100
 * Accelerating", including candidates the same report had just scored 74 and
 * marked for manual review. Two numbers beside it ("promotion cadence",
 * "retention stability") were similarly derived from role count alone.
 *
 * Everything here now comes from the dates and titles in the resume, and
 * when those aren't present the panel says so instead of showing a number.
 */
export function CareerTrajectoryPanel({ data }: { data: CareerTrajectory }) {
  if (data.status === "insufficient_data") {
    return (
      <Card>
        <CardHeader title="Career trajectory" />
        <CardBody>
          <div className="flex items-start gap-3 rounded-lg border border-line-subtle bg-canvas-inset p-4">
            <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-content-faint" />
            <div>
              <p className="text-sm text-content-muted">Not enough dated history to measure.</p>
              <p className="mt-1 text-xs leading-relaxed text-content-faint">{data.reason}</p>
            </div>
          </div>
        </CardBody>
      </Card>
    );
  }

  const years = (data.total_experience_months / 12).toFixed(1);

  return (
    <Card>
      <CardHeader
        title="Career trajectory"
        description="Derived from the employment dates and job titles on this resume."
        action={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-canvas-overlay px-2.5 py-1 text-2xs font-medium text-content-muted">
            <TrendingUp aria-hidden className="size-3" />
            {data.trajectory}
          </span>
        }
      />
      <CardBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Total experience"
            value={years}
            unit="years"
            help="Union of all role spans — concurrent roles counted once."
          />
          <Metric
            label="Median tenure"
            value={data.median_tenure_months}
            unit="months"
            help="Across completed roles. The current role is still running, so it's excluded."
          />
          <Metric
            label="Title advancements"
            value={data.advancement_steps}
            unit={
              data.months_per_advancement !== null
                ? `· one per ${data.months_per_advancement} mo`
                : undefined
            }
            help={
              data.advancement_steps === 0
                ? "No upward title change was detectable between roles."
                : "Counted where a role's title ranks above the previous one."
            }
          />
          <Metric
            label="Employment gaps"
            value={data.gap_months}
            unit="months"
            help={
              data.gap_months === 0
                ? "No unexplained gap between dated roles."
                : "Total time not covered by any dated role."
            }
          />
        </div>

        <p className="text-xs leading-relaxed text-content-faint">
          {data.basis} These are descriptive statistics about the dates on the page,
          not a prediction and not a judgement — short tenure and lateral moves are
          normal in many markets and industries.
        </p>
      </CardBody>
    </Card>
  );
}
