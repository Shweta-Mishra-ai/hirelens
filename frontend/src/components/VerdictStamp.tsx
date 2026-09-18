"use client";
import { Badge } from "@/components/ui/Badge";

/**
 * Verdict chips. These map the backend's `recommendation` field to a label a
 * recruiter can act on.
 *
 * Wording note: the labels are deliberately investigative ("Needs review"),
 * not adjudicating ("Rejected"). HireLens is decision support — the verdict
 * says what a human should do next, never what the outcome should be.
 */
export type VerdictKind = "recommended" | "manual_review" | "high_risk";

const VERDICT_META: Record<
  VerdictKind,
  { label: string; tone: "positive" | "caution" | "critical"; hint: string }
> = {
  recommended: {
    label: "Recommended",
    tone: "positive",
    hint: "Claims are consistent and evidenced — proceed to your normal screen.",
  },
  manual_review: {
    label: "Needs review",
    tone: "caution",
    hint: "Specific claims need clarification before you proceed.",
  },
  high_risk: {
    label: "High risk",
    tone: "critical",
    hint: "Multiple claims could not be reconciled — verify directly before proceeding.",
  },
};

export function verdictFromRecommendation(rec: string | null | undefined): VerdictKind {
  if (rec === "recommended" || rec === "manual_review" || rec === "high_risk") return rec;
  return "manual_review";
}

export function verdictHint(verdict: VerdictKind): string {
  return VERDICT_META[verdict].hint;
}

export function VerdictStamp({
  verdict,
  size = "md",
}: {
  verdict: VerdictKind;
  size?: "sm" | "md";
}) {
  const meta = VERDICT_META[verdict] ?? VERDICT_META.manual_review;
  return (
    <Badge tone={meta.tone} dot className={size === "md" ? "px-2.5 py-1 text-xs" : undefined}>
      {meta.label}
    </Badge>
  );
}

export function VerdictChip({ verdict }: { verdict: VerdictKind }) {
  return <VerdictStamp verdict={verdict} size="sm" />;
}
