"use client";

/**
 * VerdictStamp / VerdictChip — Modern, sleek status indicator chips.
 */

export type VerdictKind = "recommended" | "manual_review" | "high_risk";

const VERDICT_META: Record<VerdictKind, { label: string; color: string; bg: string; border: string; dot: string }> = {
  recommended:   { label: "Recommended",  color: "#5C9A6C", bg: "rgba(92, 154, 108, 0.12)", border: "rgba(92, 154, 108, 0.3)", dot: "#5C9A6C" },
  manual_review: { label: "Needs Review", color: "#B98A3E", bg: "rgba(185, 138, 62, 0.12)", border: "rgba(185, 138, 62, 0.3)", dot: "#B98A3E" },
  high_risk:     { label: "High Risk",    color: "#B3543A", bg: "rgba(179, 84, 58, 0.12)",  border: "rgba(179, 84, 58, 0.3)",  dot: "#B3543A" },
};

export function verdictFromRecommendation(rec: string): VerdictKind {
  if (rec === "recommended" || rec === "manual_review" || rec === "high_risk") return rec;
  return "manual_review";
}

export function VerdictStamp({
  verdict,
  size = "md",
}: {
  verdict: VerdictKind;
  size?: "sm" | "md" | "lg";
}) {
  const meta = VERDICT_META[verdict] || VERDICT_META.manual_review;
  const fontSize = size === "lg" ? 13 : size === "sm" ? 10 : 11;
  const padding = size === "lg" ? "6px 14px" : size === "sm" ? "2px 8px" : "4px 11px";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        color: meta.color,
        background: meta.bg,
        border: `1px solid ${meta.border}`,
        borderRadius: 9999,
        fontSize,
        padding,
        fontWeight: 600,
        letterSpacing: "0.025em",
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: meta.dot, boxShadow: `0 0 8px ${meta.dot}` }} />
      {meta.label}
    </span>
  );
}

export function VerdictChip({ verdict }: { verdict: VerdictKind }) {
  return <VerdictStamp verdict={verdict} size="sm" />;
}
