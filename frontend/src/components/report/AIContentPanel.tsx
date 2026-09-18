"use client";
import { Cpu, UserCheck, HelpCircle } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EvidenceQuote } from "./Evidence";
import type { AIContentAnalysis } from "@/types";
import { asList } from "@/lib/list";

const LIKELIHOOD = {
  low: {
    label: "Few AI-writing patterns found",
    icon: UserCheck,
    className: "text-positive",
  },
  medium: {
    label: "Mixed signals in the writing",
    icon: HelpCircle,
    className: "text-caution",
  },
  high: {
    label: "Strong AI-writing patterns found",
    icon: Cpu,
    className: "text-critical",
  },
} as const;

/**
 * AI-generated-content assessment.
 *
 * The caveat below is load-bearing, not boilerplate. A well-prompted model can
 * produce resume text with none of the tells this check looks for, so a "low"
 * result is the absence of evidence, never evidence of absence. Presenting
 * this as a verdict would invite a recruiter to reject a real person over
 * prose style, so the panel states the limit every time it renders.
 */
export function AIContentPanel({ analysis }: { analysis: AIContentAnalysis }) {
  const meta = LIKELIHOOD[analysis.likelihood] ?? LIKELIHOOD.low;
  const Icon = meta.icon;

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Icon aria-hidden className={`size-4 ${meta.className}`} />
            <span className={meta.className}>{meta.label}</span>
          </span>
        }
        description="Assessment of whether the resume text reads as AI-written"
      />
      <CardBody className="space-y-4">
        {analysis.note && (
          <p className="text-sm leading-relaxed text-content-muted">{analysis.note}</p>
        )}

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <h4 className="mb-2 text-2xs font-medium uppercase tracking-wider text-caution">
              AI-pattern indicators
            </h4>
            {asList<string>(analysis.indicators).length ? (
              <ul className="space-y-2">
                {asList<string>(analysis.indicators).map((s, i) => (
                  <li key={i} className="font-mono text-xs leading-relaxed text-content-muted">
                    <span className="mr-1.5 text-content-faint">·</span>
                    {s}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-content-faint">None found.</p>
            )}
          </div>

          <div>
            <h4 className="mb-2 text-2xs font-medium uppercase tracking-wider text-positive">
              Signs of individual authorship
            </h4>
            {asList<string>(analysis.human_indicators).length ? (
              <ul className="space-y-2">
                {asList<string>(analysis.human_indicators).map((s, i) => (
                  <li key={i} className="font-mono text-xs leading-relaxed text-content-muted">
                    <span className="mr-1.5 text-content-faint">·</span>
                    {s}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-content-faint">None found.</p>
            )}
          </div>
        </div>

        <p className="rounded-lg border border-line-subtle bg-canvas-inset px-3.5 py-3 text-xs leading-relaxed text-content-faint">
          <span className="font-medium text-content-muted">Read this carefully:</span>{" "}
          writing style is weak evidence. A capable model can be prompted to write a
          resume with none of the patterns above, so a low result means &ldquo;no strong
          textual signal&rdquo; — not &ldquo;written by a human&rdquo;. Never treat this
          section as grounds to reject a candidate on its own; use the verification
          checks and the interview instead.
        </p>
      </CardBody>
    </Card>
  );
}
