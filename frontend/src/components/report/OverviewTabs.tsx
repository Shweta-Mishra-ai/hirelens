"use client";
import {
  Briefcase,
  GraduationCap,
  FolderGit2,
  Award,
  CheckCircle2,
  HelpCircle,
  Clock,
} from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Alert, EmptyState } from "@/components/ui/Feedback";
import { EvidenceQuote } from "./Evidence";
import type {
  Education,
  Experience,
  InterviewQuestion,
  Project,
  Skills,
  TimelineGap,
} from "@/types";

/* ── Skills ─────────────────────────────────────────────────────────────── */

export function SkillsTab({ skills }: { skills: Skills }) {
  const claimed = skills.all_claimed ?? [];
  const verified = new Set(skills.verified_by_evidence ?? []);
  const unverified = skills.unverified ?? [];

  return (
    <div className="space-y-5">
      {skills.domain_spread_concern && skills.domain_spread_note && (
        <Alert tone="warning" title="Unusually wide domain spread">
          {skills.domain_spread_note}
        </Alert>
      )}

      <Card>
        <CardHeader
          title="Skills evidenced in work history"
          description="These appear in a role or project description, not only in a skills list."
          action={
            <Badge tone="positive">
              {verified.size} of {claimed.length}
            </Badge>
          }
        />
        <CardBody>
          {verified.size === 0 ? (
            <p className="text-sm text-content-faint">
              No claimed skill appeared in any role or project description.
            </p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {[...verified].map((s) => (
                <Badge key={s} tone="positive" icon={<CheckCircle2 className="size-3" />}>
                  {s}
                </Badge>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Listed but not evidenced"
          description="Present in the skills list with no supporting mention in the work history."
          action={<Badge tone="neutral">{unverified.length}</Badge>}
        />
        <CardBody className="space-y-3">
          {unverified.length === 0 ? (
            <p className="text-sm text-content-faint">
              Every listed skill is backed by something in the work history.
            </p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {unverified.map((s) => (
                <Badge key={s} tone="caution" icon={<HelpCircle className="size-3" />}>
                  {s}
                </Badge>
              ))}
            </div>
          )}
          <p className="text-xs leading-relaxed text-content-faint">
            An unevidenced skill is a question, not a finding. People routinely omit
            tools they use daily, and a one-page resume cannot mention everything —
            ask about these rather than discounting them.
          </p>
        </CardBody>
      </Card>

      {skills.primary_domain && (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-2xs font-medium uppercase tracking-wider text-content-faint">
                Primary domain
              </div>
              <div className="mt-1 text-sm text-content">{skills.primary_domain}</div>
            </div>
            {skills.keyword_stuffing_risk && skills.keyword_stuffing_risk !== "none" && (
              <Badge
                tone={skills.keyword_stuffing_risk === "high" ? "critical" : "caution"}
              >
                Keyword density: {skills.keyword_stuffing_risk}
              </Badge>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

/* ── Timeline ───────────────────────────────────────────────────────────── */

export function TimelineTab({
  experience,
  education,
  projects,
  certifications,
  gaps,
}: {
  experience: Experience[];
  education: Education[];
  projects: Project[];
  certifications: string[];
  gaps: TimelineGap[];
}) {
  return (
    <div className="space-y-5">
      {gaps.length > 0 && (
        <Card>
          <CardHeader
            title="Employment gaps"
            description="Periods not covered by a listed role. Gaps are normal — caregiving, study, illness, redundancy, travel — and are listed here only so you know to ask."
          />
          <CardBody className="space-y-2">
            {gaps.map((g, i) => (
              <div
                key={i}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-canvas-inset px-3.5 py-2.5"
              >
                <Clock aria-hidden className="size-3.5 shrink-0 text-content-faint" />
                <span className="font-mono text-xs text-content-muted">
                  {g.from} → {g.to}
                </span>
                <Badge tone="neutral">{g.duration}</Badge>
                {g.note && <span className="text-xs text-content-faint">{g.note}</span>}
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Work history" action={<Badge tone="neutral">{experience.length}</Badge>} />
        <CardBody>
          {experience.length === 0 ? (
            <EmptyState icon={<Briefcase className="size-5" />} title="No roles extracted" className="py-8" />
          ) : (
            <ol className="relative space-y-6 border-l border-line pl-5">
              {experience.map((e, i) => (
                <li key={i} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[1.4375rem] top-1.5 size-2 rounded-full border-2 border-canvas bg-line-strong"
                  />
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-sm font-medium text-content">{e.role}</h3>
                    <span className="font-mono text-xs text-content-faint">{e.period}</span>
                  </div>
                  <div className="mt-0.5 text-sm text-content-muted">{e.company}</div>

                  {e.responsibilities && e.responsibilities.length > 0 && (
                    <ul className="mt-2.5 space-y-1.5">
                      {e.responsibilities.map((r, j) => (
                        <li key={j} className="flex gap-2 text-sm leading-relaxed text-content-muted">
                          <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-content-faint" />
                          {r}
                        </li>
                      ))}
                    </ul>
                  )}

                  {e.technologies && e.technologies.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {e.technologies.map((t) => (
                        <Badge key={t} tone="neutral">{t}</Badge>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Education" action={<Badge tone="neutral">{education.length}</Badge>} />
          <CardBody>
            {education.length === 0 ? (
              <EmptyState icon={<GraduationCap className="size-5" />} title="None listed" className="py-8" />
            ) : (
              <ul className="space-y-4">
                {education.map((e, i) => (
                  <li key={i}>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-sm font-medium text-content">{e.degree}</span>
                      {e.period && (
                        <span className="font-mono text-xs text-content-faint">{e.period}</span>
                      )}
                    </div>
                    <div className="mt-0.5 text-sm text-content-muted">{e.institution}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {e.field && <Badge tone="neutral">{e.field}</Badge>}
                      {e.grade && <Badge tone="neutral">{e.grade}</Badge>}
                    </div>
                    {e.concern && (
                      <p className="mt-2 text-xs leading-relaxed text-caution">{e.concern}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Projects" action={<Badge tone="neutral">{projects.length}</Badge>} />
          <CardBody>
            {projects.length === 0 ? (
              <EmptyState icon={<FolderGit2 className="size-5" />} title="None listed" className="py-8" />
            ) : (
              <ul className="space-y-4">
                {projects.map((p, i) => (
                  <li key={i}>
                    <div className="text-sm font-medium text-content">{p.name}</div>
                    <p className="mt-1 text-sm leading-relaxed text-content-muted">
                      {p.description}
                    </p>
                    {p.technologies?.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {p.technologies.map((t) => (
                          <Badge key={t} tone="neutral">{t}</Badge>
                        ))}
                      </div>
                    )}
                    {p.metrics?.length > 0 && (
                      <EvidenceQuote label="Claimed metrics" className="mt-2">
                        {p.metrics.join(" · ")}
                      </EvidenceQuote>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      {certifications.length > 0 && (
        <Card>
          <CardHeader
            title="Certifications"
            action={<Badge tone="neutral">{certifications.length}</Badge>}
          />
          <CardBody>
            <ul className="space-y-2">
              {certifications.map((c, i) => (
                <li key={i} className="flex items-center gap-2.5 text-sm text-content-muted">
                  <Award aria-hidden className="size-3.5 shrink-0 text-content-faint" />
                  {c}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

/* ── Interview questions ────────────────────────────────────────────────── */

const CATEGORY_TONE = {
  technical: "info",
  clarification: "caution",
  behavioral: "brand",
} as const;

export function QuestionsTab({ questions }: { questions: InterviewQuestion[] }) {
  if (questions.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<HelpCircle className="size-5" />}
          title="No questions generated"
          description="Questions are written against the specific concerns raised for this candidate."
        />
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Suggested interview questions"
        description="Written against this candidate's specific claims and flags. Use the Co-Pilot tab to work through them live."
        action={<Badge tone="neutral">{questions.length}</Badge>}
      />
      <CardBody>
        <ol className="space-y-5">
          {questions.map((q, i) => (
            <li key={i} className="flex gap-3.5">
              <span className="mt-0.5 w-5 shrink-0 text-sm tabular text-content-faint">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-relaxed text-content">{q.question}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {q.category && (
                    <Badge tone={CATEGORY_TONE[q.category] ?? "neutral"} className="capitalize">
                      {q.category}
                    </Badge>
                  )}
                  {q.targets_flag && <Badge tone="neutral">Addresses: {q.targets_flag}</Badge>}
                </div>
                {q.rationale && (
                  <p className="mt-1.5 text-xs leading-relaxed text-content-faint">
                    {q.rationale}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}
