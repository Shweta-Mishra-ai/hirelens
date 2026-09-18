"use client";
import { useState } from "react";
import {
  Check,
  X,
  Minus,
  AlertTriangle,
  HelpCircle,
  Clock,
  Github,
  GraduationCap,
  Award,
  Building2,
  ShieldCheck,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Field";
import { Alert, EmptyState } from "@/components/ui/Feedback";
import { absoluteTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import type {
  CertificationVerification,
  EducationVerification,
  ExperienceVerification,
  VerificationResult,
} from "@/types";
import { asList } from "@/lib/list";

type Tone = "positive" | "caution" | "critical" | "neutral";

interface StatusMeta {
  label: string;
  tone: Tone;
  icon: React.ReactNode;
}

const ICONS = {
  ok: <Check className="size-3" strokeWidth={3} />,
  no: <X className="size-3" strokeWidth={3} />,
  dash: <Minus className="size-3" />,
  wait: <Clock className="size-3" />,
  warn: <AlertTriangle className="size-3" />,
  unknown: <HelpCircle className="size-3" />,
};

/**
 * Status vocabulary for each check.
 *
 * "Not found" is deliberately never styled as `critical`. An absent GitHub
 * account or an institution missing from a domain registry says something
 * about our data sources, not about the candidate — plenty of real engineers
 * have no public repos, and the registry skews heavily towards US and
 * European institutions. Colouring those red would push recruiters to treat
 * a coverage gap as a finding against the person.
 */
const GITHUB_STATUS: Record<string, StatusMeta> = {
  verified: { label: "Verified", tone: "positive", icon: ICONS.ok },
  partial: { label: "Partial match", tone: "caution", icon: ICONS.wait },
  no_public_activity: { label: "No public repos", tone: "neutral", icon: ICONS.dash },
  not_found: { label: "Account not found", tone: "caution", icon: ICONS.unknown },
  no_username: { label: "No username on resume", tone: "neutral", icon: ICONS.dash },
  rate_limited: { label: "Rate limited — try again", tone: "neutral", icon: ICONS.wait },
  error: { label: "Check failed", tone: "neutral", icon: ICONS.warn },
};

// "In registry", not "Verified". This check confirms the institution exists
// in an open registry under the name on the resume — it says nothing about
// whether the candidate attended it, and a badge reading "Verified" next to a
// degree claim is read as though it does.
const EDU_STATUS: Record<string, StatusMeta> = {
  verified: { label: "In registry", tone: "positive", icon: ICONS.ok },
  possible_match: { label: "Similar name only", tone: "caution", icon: ICONS.wait },
  not_found: { label: "Not in registry", tone: "neutral", icon: ICONS.unknown },
  skipped: { label: "Skipped", tone: "neutral", icon: ICONS.dash },
  error: { label: "Check failed", tone: "neutral", icon: ICONS.warn },
};

const CERT_STATUS: Record<string, StatusMeta> = {
  verified_via_link: { label: "Verified", tone: "positive", icon: ICONS.ok },
  link_reachable_name_not_confirmed: {
    label: "Link works, name unconfirmed",
    tone: "caution",
    icon: ICONS.wait,
  },
  link_unreachable: { label: "Link unreachable", tone: "caution", icon: ICONS.no },
  no_link_provided: { label: "No link on resume", tone: "neutral", icon: ICONS.dash },
  error: { label: "Check failed", tone: "neutral", icon: ICONS.warn },
};

const EXP_STATUS: Record<string, StatusMeta> = {
  domain_found: { label: "Website found", tone: "positive", icon: ICONS.ok },
  domain_not_found: { label: "No website found", tone: "neutral", icon: ICONS.unknown },
  skipped: { label: "Skipped", tone: "neutral", icon: ICONS.dash },
};

function StatusBadge({ meta }: { meta: StatusMeta | undefined }) {
  const m = meta ?? { label: "Unknown", tone: "neutral" as Tone, icon: ICONS.unknown };
  return (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label}
    </Badge>
  );
}

function CheckRow({
  primary,
  secondary,
  status,
  note,
  href,
}: {
  primary: string;
  secondary?: string;
  status: StatusMeta | undefined;
  note?: string;
  href?: string;
}) {
  return (
    <li className="flex flex-wrap items-start gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm text-content">{primary}</span>
          {href && (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-content-faint transition-colors hover:text-brand-400"
              aria-label={`Open ${primary} in a new tab`}
            >
              <ExternalLink className="size-3" />
            </a>
          )}
        </div>
        {secondary && (
          <div className="truncate font-mono text-xs text-content-faint">{secondary}</div>
        )}
        {note && <p className="mt-1 text-xs leading-relaxed text-content-faint">{note}</p>}
      </div>
      <StatusBadge meta={status} />
    </li>
  );
}

function Group({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: typeof Github;
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-canvas-raised">
      <div className="flex items-center gap-2 border-b border-line-subtle px-4 py-2.5">
        <Icon aria-hidden className="size-4 text-content-faint" />
        <h3 className="text-sm font-medium text-content">{title}</h3>
        {count !== undefined && (
          <span className="text-xs tabular text-content-faint">{count}</span>
        )}
      </div>
      <div className="px-4 py-1">{children}</div>
    </div>
  );
}

const TRUST_META: Record<string, { label: string; tone: Tone }> = {
  high_confidence: { label: "Evidence supports this resume", tone: "positive" },
  moderate_confidence: { label: "Partially corroborated", tone: "caution" },
  low_confidence: { label: "Evidence does not line up", tone: "critical" },
  insufficient_evidence: { label: "Not enough public evidence", tone: "neutral" },
};

export function VerifyPanel({
  verification,
  loading,
  error,
  githubOverride,
  onGithubOverrideChange,
  onRun,
}: {
  verification: VerificationResult | null;
  loading: boolean;
  error: string | null;
  githubOverride: string;
  onGithubOverrideChange: (v: string) => void;
  onRun: () => void;
}) {
  const [showOverride, setShowOverride] = useState(false);

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Public-record verification"
          description="Live checks against GitHub, university domain registries, certificate links and company websites. Run on demand — nothing is cached."
          action={
            <Button
              variant="primary"
              size="sm"
              loading={loading}
              icon={<RefreshCw className="size-3.5" />}
              onClick={onRun}
            >
              {verification ? "Re-run checks" : "Run checks"}
            </Button>
          }
        />
        <CardBody className="space-y-3">
          <button
            type="button"
            onClick={() => setShowOverride((v) => !v)}
            className="text-xs text-brand-400 underline-offset-4 hover:underline"
          >
            {showOverride ? "Hide" : "GitHub username wrong or missing?"}
          </button>
          {showOverride && (
            <Input
              label="GitHub username override"
              value={githubOverride}
              onChange={(e) => onGithubOverrideChange(e.target.value)}
              placeholder="octocat"
              hint={
                <span className="text-xs text-content-faint">
                  Used instead of the one parsed from the resume
                </span>
              }
            />
          )}
          {verification && (
            <p className="text-xs text-content-faint">
              Last run {absoluteTime(verification.run_at)}
            </p>
          )}
        </CardBody>
      </Card>

      {error && <Alert tone="error">{error}</Alert>}

      {!verification && !loading && (
        <Card>
          <EmptyState
            icon={<ShieldCheck className="size-5" />}
            title="No checks run yet"
            description="Verification calls external services in real time, so it runs only when you ask for it."
          />
        </Card>
      )}

      {verification && (
        <>
          {verification.trust_assessment && (
            <Card>
              <CardHeader
                title="Combined trust assessment"
                description="A fixed rule set over the check results above — not another model judgement."
                action={
                  <StatusBadge
                    meta={{
                      ...(TRUST_META[verification.trust_assessment.verdict] ??
                        TRUST_META.insufficient_evidence),
                      icon: <ShieldCheck className="size-3" />,
                    }}
                  />
                }
              />
              <CardBody className="space-y-3">
                {!verification.trust_assessment.evidence_available && (
                  <p className="text-sm leading-relaxed text-content-muted">
                    Nothing independently verifiable was found either way. That is not a
                    red flag — it means public data alone can neither support nor dispute
                    this resume. Weigh it accordingly.
                  </p>
                )}
                {asList<string>(verification.trust_assessment?.reasoning).length > 0 && (
                  <details className="group">
                    <summary className="cursor-pointer text-xs font-medium text-brand-400 marker:content-none">
                      Show the {asList<string>(verification.trust_assessment?.reasoning).length} signals
                      considered
                    </summary>
                    <ul className="mt-2 space-y-1.5">
                      {asList<string>(verification.trust_assessment?.reasoning).map((r, i) => (
                        <li key={i} className="text-xs leading-relaxed text-content-faint">
                          <span className="mr-1.5">·</span>
                          {r}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </CardBody>
            </Card>
          )}

          {verification.recommendation_update && (
            <Alert tone="info" title="Verification changed the recommendation">
              {verification.recommendation_update.reason}
            </Alert>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Group icon={Github} title="GitHub">
              {verification.github.status === "no_username" ? (
                <p className="py-3 text-xs text-content-faint">
                  No GitHub profile was found on this resume.
                </p>
              ) : (
                <ul className="divide-y divide-line-subtle">
                  <CheckRow
                    primary={verification.github.username ?? "Unknown account"}
                    secondary={
                      verification.github.public_repos !== undefined
                        ? `${verification.github.public_repos} public repos`
                        : undefined
                    }
                    status={GITHUB_STATUS[verification.github.status]}
                    note={verification.github.note}
                    href={verification.github.profile_url}
                  />
                  {(verification.github.verified_skills?.length ||
                    verification.github.unverified_skills?.length) && (
                    <li className="space-y-2.5 py-3">
                      {verification.github.verified_skills?.length ? (
                        <div>
                          <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-positive">
                            Evidenced in public repos
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {asList<string>(verification.github?.verified_skills).map((s) => (
                              <Badge key={s} tone="positive">{s}</Badge>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {verification.github.unverified_skills?.length ? (
                        <div>
                          <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-content-faint">
                            Not seen in public repos
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {asList<string>(verification.github?.unverified_skills).map((s) => (
                              <Badge key={s} tone="neutral">{s}</Badge>
                            ))}
                          </div>
                          <p className="mt-1.5 text-xs text-content-faint">
                            Most professional work lives in private repositories. Absence
                            here is not evidence the skill is fabricated.
                          </p>
                        </div>
                      ) : null}
                    </li>
                  )}
                </ul>
              )}
            </Group>

            <Group
              icon={GraduationCap}
              title="Education"
              count={asList(verification.education).length}
            >
              {asList(verification.education).length === 0 ? (
                <p className="py-3 text-xs text-content-faint">
                  No institutions were listed on this resume.
                </p>
              ) : (
                <ul className="divide-y divide-line-subtle">
                  {asList<EducationVerification>(verification.education).map((e, i) => (
                    <CheckRow
                      key={i}
                      primary={e.institution ?? "Unnamed institution"}
                      secondary={e.matched_name ?? e.domain}
                      status={EDU_STATUS[e.status]}
                      note={e.note}
                    />
                  ))}
                </ul>
              )}
            </Group>

            <Group
              icon={Award}
              title="Certifications"
              count={asList(verification.certifications).length}
            >
              {asList(verification.certifications).length === 0 ? (
                <p className="py-3 text-xs text-content-faint">
                  No certifications were listed on this resume.
                </p>
              ) : (
                <ul className="divide-y divide-line-subtle">
                  {asList<CertificationVerification>(verification.certifications).map((c, i) => (
                    <CheckRow
                      key={i}
                      primary={c.name}
                      status={CERT_STATUS[c.status]}
                      note={c.note}
                      href={c.url}
                    />
                  ))}
                </ul>
              )}
            </Group>

            <Group icon={Building2} title="Employers" count={asList(verification.experience).length}>
              {asList(verification.experience).length === 0 ? (
                <p className="py-3 text-xs text-content-faint">
                  No employers were listed on this resume.
                </p>
              ) : (
                <ul className="divide-y divide-line-subtle">
                  {asList<ExperienceVerification>(verification.experience).map((x, i) => (
                    <CheckRow
                      key={i}
                      primary={x.company ?? "Unnamed company"}
                      secondary={x.domain_checked}
                      status={EXP_STATUS[x.status]}
                      note={x.note}
                    />
                  ))}
                </ul>
              )}
            </Group>
          </div>

          <p className="text-xs leading-relaxed text-content-faint">
            These checks confirm that public records exist and are consistent with the
            resume. They cannot confirm employment, and a &ldquo;not found&rdquo; result
            most often reflects the limits of public data rather than anything about the
            candidate.
          </p>
        </>
      )}
    </div>
  );
}
