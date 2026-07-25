"use client";
/**
 * VerdictStamp — HireLens's signature visual element.
 *
 * Every other resume-screening tool shows a score as a circular progress
 * ring or a soft pill badge. HireLens is a *credibility examination* tool —
 * so its verdict reads like an ink stamp on a case file: rotated, bordered,
 * decisive. Used consistently wherever a recommendation is shown: report
 * headers, dashboard rows, ranking tables.
 */

export type VerdictKind = "recommended" | "manual_review" | "high_risk";

const VERDICT_META: Record<VerdictKind, { label: string; color: string; rotation: string }> = {
  recommended:   { label: "Recommended",     color: "var(--stamp-green-l)", rotation: "-3deg" },
  manual_review: { label: "Needs Review",    color: "var(--stamp-gold-l)",  rotation: "-5deg" },
  high_risk:     { label: "High Risk",       color: "var(--stamp-red-l)",  rotation: "-2deg" },
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
  const meta = VERDICT_META[verdict];
  const fontSize = size === "lg" ? 15 : size === "sm" ? 10 : 12;
  const padding = size === "lg" ? "6px 16px" : size === "sm" ? "2px 8px" : "3px 10px";

  return (
    <span
      className="stamp"
      style={
        {
          "--stamp-rot": meta.rotation,
          color: meta.color,
          fontSize,
          padding,
        } as React.CSSProperties
      }
    >
      {meta.label}
    </span>
  );
}

/** Compact inline variant for dense table rows — same identity, no rotation
 * animation replay per-row (keeps long lists calm rather than busy). */
export function VerdictChip({ verdict }: { verdict: VerdictKind }) {
  const meta = VERDICT_META[verdict];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontFamily: "var(--font-display), Georgia, serif",
        fontWeight: 700,
        fontSize: 10,
        letterSpacing: "0.05em",
        textTransform: "uppercase",
        color: meta.color,
        border: `1.5px solid ${meta.color}`,
        borderRadius: 3,
        padding: "2px 8px",
        transform: `rotate(${meta.rotation})`,
        whiteSpace: "nowrap",
      }}
    >
      {meta.label}
    </span>
  );
}
