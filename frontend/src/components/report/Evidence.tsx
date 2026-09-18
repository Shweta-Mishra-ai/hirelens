"use client";
import { Quote } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * A verbatim quote from the candidate's resume.
 *
 * Evidence is the whole premise of the product — a flag a recruiter can't
 * trace back to the source text is just an assertion — so quotes get a
 * distinct, deliberately plain treatment: monospace, a quote rule, and no
 * colour of their own, so the words read as the candidate's rather than as
 * part of the system's judgement.
 */
export function EvidenceQuote({
  children,
  className,
  label = "From the resume",
}: {
  children: React.ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <figure className={cn("my-2", className)}>
      <figcaption className="mb-1 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-content-faint">
        <Quote aria-hidden className="size-3" />
        {label}
      </figcaption>
      <blockquote className="border-l-2 border-line-strong bg-canvas-inset py-2 pl-3 pr-3 font-mono text-xs leading-relaxed text-content-muted">
        {children}
      </blockquote>
    </figure>
  );
}
