"use client";
import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Mail,
  Pencil,
  Send,
  ThumbsUp,
  ThumbsDown,
  CalendarClock,
  Github,
  Linkedin,
  MapPin,
  ShieldCheck,
  Sparkles,
  ScanLine,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import {
  reportsAPI,
  verifyAPI,
  teamsAPI,
  collaborationAPI,
  copilotAPI,
  APIError,
} from "@/lib/api";
import type {
  Report,
  SubScores,
  Decision,
  VerificationResult,
  Team,
  ReportComment,
  VotesResult,
} from "@/types";
import { VerdictStamp, verdictFromRecommendation, verdictHint } from "@/components/VerdictStamp";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input, Textarea } from "@/components/ui/Field";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Feedback";
import { Tabs, TabPanel, type TabItem } from "@/components/ui/Tabs";
import { ScoreRing, ScoreBar } from "@/components/ui/Score";
import { AIContentPanel } from "@/components/report/AIContentPanel";
import { CareerTrajectoryPanel } from "@/components/report/CareerTrajectoryPanel";
import { FlagCard, FlagSummary } from "@/components/report/FlagCard";
import { VerifyPanel } from "@/components/report/VerifyPanel";
import { CopilotPanel, type ProbeQuestion, type ScorecardItem } from "@/components/report/CopilotPanel";
import { DiscussPanel } from "@/components/report/DiscussPanel";
import { SkillsTab, TimelineTab, QuestionsTab } from "@/components/report/OverviewTabs";
import { absoluteTime } from "@/lib/format";
import { cn } from "@/lib/cn";

// Keyed by SubScores so a renamed or added dimension is a compile error here
// rather than a silently missing row in the breakdown.
const SUB_SCORE_LABELS: Record<keyof SubScores, string> = {
  timeline: "Employment timeline",
  skills_consistency: "Skills consistency",
  education: "Education",
  project_authenticity: "Project authenticity",
  resume_quality: "Resume quality",
  content_authenticity: "Content authenticity",
};

const DECISIONS: { value: Decision; label: string; icon: typeof ThumbsUp; tone: string }[] = [
  { value: "advance", label: "Advance", icon: ThumbsUp, tone: "border-positive-line bg-positive-soft text-positive" },
  { value: "schedule_followup", label: "Follow up", icon: CalendarClock, tone: "border-caution-line bg-caution-soft text-caution" },
  { value: "reject", label: "Not a match", icon: ThumbsDown, tone: "border-critical-line bg-critical-soft text-critical" },
];

const DEFAULT_SCORECARD: ScorecardItem[] = [
  { category: "technical_depth", label: "Technical depth", score: 0, notes: "" },
  { category: "problem_solving", label: "Problem solving", score: 0, notes: "" },
  { category: "culture_fit", label: "Ways of working", score: 0, notes: "" },
  { category: "authenticity", label: "Consistency with the resume", score: 0, notes: "" },
];

function ReportContent() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { user, token, logout } = useAuthStore();

  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");

  // Decision + candidate notification
  const [decision, setDecision] = useState<Decision | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [notifyState, setNotifyState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [notifyMessage, setNotifyMessage] = useState<string | null>(null);
  const [notifyEditorOpen, setNotifyEditorOpen] = useState(false);
  const [notifyDraftLoading, setNotifyDraftLoading] = useState(false);
  const [notifyDraft, setNotifyDraft] = useState<{
    subject: string;
    body: string;
    candidate_email: string | null;
    has_email: boolean;
  } | null>(null);

  // Verification
  const [verification, setVerification] = useState<VerificationResult | null>(null);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [githubOverride, setGithubOverride] = useState("");

  // Collaboration
  const [myTeams, setMyTeams] = useState<Team[]>([]);
  const [comments, setComments] = useState<ReportComment[]>([]);
  const [newComment, setNewComment] = useState("");
  const [postingComment, setPostingComment] = useState(false);
  const [votesResult, setVotesResult] = useState<VotesResult | null>(null);
  const [discussLoading, setDiscussLoading] = useState(false);
  const [discussError, setDiscussError] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  // Co-pilot
  const [scorecard, setScorecard] = useState<ScorecardItem[]>(DEFAULT_SCORECARD);
  const [copilotQuestions, setCopilotQuestions] = useState<ProbeQuestion[]>([]);
  const [newProbeQuestion, setNewProbeQuestion] = useState("");
  const [interviewNotes, setInterviewNotes] = useState("");
  const [copilotSaving, setCopilotSaving] = useState(false);
  const [copilotSuccess, setCopilotSuccess] = useState(false);
  const [copilotError, setCopilotError] = useState<string | null>(null);

  /* ── Load ─────────────────────────────────────────────────────────────── */

  useEffect(() => {
    if (!token || !params.id) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await reportsAPI.get(params.id, token);
        if (cancelled) return;
        setReport(r);
        setDecision(r.recruiter_decision);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof APIError && e.status === 401) {
          logout();
          router.replace("/login");
          return;
        }
        setError(e instanceof APIError ? e.message : "Could not load this report.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.id, token, logout, router]);

  // A 404 here just means verification hasn't been run — not an error state.
  useEffect(() => {
    if (!token || !params.id) return;
    verifyAPI
      .get(params.id, token)
      .then(setVerification)
      .catch(() => {});
  }, [params.id, token]);

  /* ── Decision ─────────────────────────────────────────────────────────── */

  const submitDecision = useCallback(
    async (d: Decision) => {
      if (!token || !params.id) return;
      const previous = decision;
      setDecision(d);
      setDecisionError(null);
      setNotifyState("idle");
      setNotifyMessage(null);
      try {
        await reportsAPI.decision(params.id, d, undefined, token);
      } catch (e) {
        // Roll back the optimistic update — a decision that failed to save
        // must never be left on screen looking recorded.
        setDecision(previous);
        setDecisionError(
          e instanceof APIError ? e.message : "Could not save that decision. Try again.",
        );
      }
    },
    [token, params.id, decision],
  );

  const sendDefaultNotification = useCallback(async () => {
    if (!token || !params.id || !decision) return;
    setNotifyState("sending");
    setNotifyMessage(null);
    try {
      const draft = await reportsAPI.notifyDraft(params.id, decision, token);
      if (!draft.has_email || !draft.candidate_email) {
        setNotifyState("error");
        setNotifyMessage("No email address was found on this resume. Use Edit to add one.");
        return;
      }
      const result = await reportsAPI.notify(params.id, decision, draft.subject, draft.body, token);
      if (result.email_sent) {
        setNotifyState("sent");
        setNotifyMessage(`Email sent to ${result.candidate_email}.`);
      } else {
        setNotifyState("error");
        setNotifyMessage(result.message);
      }
    } catch (e) {
      setNotifyState("error");
      setNotifyMessage(e instanceof APIError ? e.message : "Could not send the email.");
    }
  }, [token, params.id, decision]);

  const openNotifyEditor = useCallback(async () => {
    if (!token || !params.id || !decision) return;
    setNotifyDraftLoading(true);
    setNotifyMessage(null);
    try {
      setNotifyDraft(await reportsAPI.notifyDraft(params.id, decision, token));
      setNotifyEditorOpen(true);
    } catch (e) {
      setNotifyState("error");
      setNotifyMessage(e instanceof APIError ? e.message : "Could not load the draft.");
    } finally {
      setNotifyDraftLoading(false);
    }
  }, [token, params.id, decision]);

  const sendEditedNotification = useCallback(async () => {
    if (!token || !params.id || !decision || !notifyDraft) return;
    setNotifyState("sending");
    setNotifyMessage(null);
    try {
      const result = await reportsAPI.notify(
        params.id,
        decision,
        notifyDraft.subject,
        notifyDraft.body,
        token,
      );
      if (result.email_sent) {
        setNotifyState("sent");
        setNotifyMessage(`Email sent to ${result.candidate_email}.`);
        setNotifyEditorOpen(false);
      } else {
        setNotifyState("error");
        setNotifyMessage(result.message);
      }
    } catch (e) {
      setNotifyState("error");
      setNotifyMessage(e instanceof APIError ? e.message : "Could not send the email.");
    }
  }, [token, params.id, decision, notifyDraft]);

  /* ── Verification ─────────────────────────────────────────────────────── */

  const runVerification = useCallback(async () => {
    if (!token || !params.id) return;
    setVerifyLoading(true);
    setVerifyError(null);
    try {
      const v = await verifyAPI.run(params.id, githubOverride.trim() || undefined, token);
      setVerification(v);
      if (v.recommendation_update) {
        const update = v.recommendation_update;
        setReport((prev) =>
          prev
            ? {
                ...prev,
                credibility: {
                  ...prev.credibility,
                  recommendation: update.new_recommendation,
                  ai_recommendation: update.ai_recommendation,
                  recommendation_adjusted_by_verification: true,
                  recommendation_adjustment_reason: update.reason,
                },
              }
            : prev,
        );
      }
    } catch (e) {
      setVerifyError(e instanceof APIError ? e.message : "Verification failed. Try again.");
    } finally {
      setVerifyLoading(false);
    }
  }, [token, params.id, githubOverride]);

  /* ── Collaboration ────────────────────────────────────────────────────── */

  const loadDiscussData = useCallback(async () => {
    if (!token || !params.id) return;
    setDiscussLoading(true);
    setDiscussError(null);
    try {
      const [commentsRes, votesRes, teamsRes] = await Promise.all([
        collaborationAPI.listComments(params.id, token),
        collaborationAPI.listVotes(params.id, token),
        teamsAPI.list(token).catch(() => ({ teams: [] as Team[] })),
      ]);
      setComments(commentsRes.comments);
      setVotesResult(votesRes);
      setMyTeams(teamsRes.teams);
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not load the discussion.");
    } finally {
      setDiscussLoading(false);
    }
  }, [token, params.id]);

  useEffect(() => {
    if (tab === "discuss") void loadDiscussData();
  }, [tab, loadDiscussData]);

  const postComment = useCallback(async () => {
    if (!token || !params.id || !newComment.trim()) return;
    setPostingComment(true);
    try {
      const c = await collaborationAPI.addComment(params.id, newComment.trim(), token);
      setComments((prev) => [...prev, c]);
      setNewComment("");
    } catch (e) {
      setDiscussError(e instanceof APIError ? e.message : "Could not post that comment.");
    } finally {
      setPostingComment(false);
    }
  }, [token, params.id, newComment]);

  const removeComment = useCallback(
    async (commentId: string) => {
      if (!token || !params.id) return;
      try {
        await collaborationAPI.deleteComment(params.id, commentId, token);
        setComments((prev) => prev.filter((c) => c.id !== commentId));
      } catch (e) {
        setDiscussError(e instanceof APIError ? e.message : "Could not delete that comment.");
      }
    },
    [token, params.id],
  );

  const castVote = useCallback(
    async (vote: "advance" | "reject" | "maybe") => {
      if (!token || !params.id) return;
      try {
        await collaborationAPI.vote(params.id, vote, token);
        setVotesResult(await collaborationAPI.listVotes(params.id, token));
      } catch (e) {
        setDiscussError(e instanceof APIError ? e.message : "Could not record your vote.");
      }
    },
    [token, params.id],
  );

  const shareWithTeam = useCallback(
    async (teamId: string) => {
      if (!token || !params.id) return;
      setSharing(true);
      try {
        await collaborationAPI.share(params.id, teamId, token);
        setReport((prev) => (prev ? { ...prev, team_id: teamId } : prev));
      } catch (e) {
        setDiscussError(e instanceof APIError ? e.message : "Could not share this report.");
      } finally {
        setSharing(false);
      }
    },
    [token, params.id],
  );

  /* ── Co-pilot ─────────────────────────────────────────────────────────── */

  const loadCopilotData = useCallback(async () => {
    if (!token || !params.id) return;
    setCopilotError(null);

    const seedFromReport = (): ProbeQuestion[] =>
      (report?.interview_questions ?? []).map((q) => ({
        question: q.question,
        category: q.category,
        is_asked: false,
      }));

    try {
      const res = await copilotAPI.get(params.id, token);
      const c = res?.copilot;
      if (!c) {
        setCopilotQuestions((prev) => (prev.length ? prev : seedFromReport()));
        return;
      }
      if (Array.isArray(c.scorecard) && c.scorecard.length > 0) {
        setScorecard((prev) =>
          prev.map((item) => {
            const found = c.scorecard.find(
              (s: { category: string }) => s.category === item.category,
            );
            return found ? { ...item, score: found.score ?? 0, notes: found.notes ?? "" } : item;
          }),
        );
      }
      setCopilotQuestions(
        Array.isArray(c.custom_questions) && c.custom_questions.length > 0
          ? c.custom_questions
          : seedFromReport(),
      );
      if (c.interview_notes) setInterviewNotes(c.interview_notes);
    } catch {
      // No saved co-pilot state yet — start from the report's questions.
      setCopilotQuestions((prev) => (prev.length ? prev : seedFromReport()));
    }
  }, [token, params.id, report]);

  useEffect(() => {
    if (tab === "copilot") void loadCopilotData();
  }, [tab, loadCopilotData]);

  const saveCopilotData = useCallback(async () => {
    if (!token || !params.id) return;
    setCopilotSaving(true);
    setCopilotError(null);
    setCopilotSuccess(false);
    try {
      await copilotAPI.save(
        params.id,
        {
          scorecard: scorecard.map((s) => ({
            category: s.category,
            score: s.score,
            notes: s.notes,
          })),
          custom_questions: copilotQuestions,
          interview_notes: interviewNotes,
          recommendation_override: decision || undefined,
        },
        token,
      );
      setCopilotSuccess(true);
      const t = setTimeout(() => setCopilotSuccess(false), 3500);
      return () => clearTimeout(t);
    } catch (e) {
      setCopilotError(e instanceof APIError ? e.message : "Could not save the scorecard.");
    } finally {
      setCopilotSaving(false);
    }
  }, [token, params.id, scorecard, copilotQuestions, interviewNotes, decision]);

  /* ── Render ───────────────────────────────────────────────────────────── */

  if (loading) {
    return (
      <AppShell>
        <Skeleton className="mb-6 h-8 w-48" />
        <Skeleton className="mb-5 h-44" />
        <Skeleton className="h-96" />
      </AppShell>
    );
  }

  if (error || !report) {
    return (
      <AppShell width="narrow">
        <Card>
          <EmptyState
            icon={<ScanLine className="size-5" />}
            title={error ?? "Report not found"}
            description="It may have been deleted, or the link may be wrong."
            action={
              <Link href="/dashboard">
                <Button variant="primary">Back to dashboard</Button>
              </Link>
            }
          />
        </Card>
      </AppShell>
    );
  }

  const cred = report.credibility;
  const scores = cred?.sub_scores;
  const rationale = cred?.score_rationale ?? {};
  const flags = report.flags ?? [];
  const candidate = report.candidate ?? {};
  const verdict = verdictFromRecommendation(cred?.recommendation);

  const TABS: TabItem[] = [
    { id: "overview", label: "Overview" },
    { id: "flags", label: "Flags", count: flags.length },
    { id: "skills", label: "Skills" },
    { id: "timeline", label: "History" },
    { id: "verify", label: "Verify" },
    { id: "questions", label: "Questions", count: report.interview_questions?.length ?? 0 },
    { id: "copilot", label: "Co-Pilot" },
    { id: "discuss", label: "Discuss" },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 text-xs text-content-faint transition-colors hover:text-content-muted"
          >
            <ArrowLeft aria-hidden className="size-3.5" />
            All candidates
          </Link>
        }
        title={candidate.name || "Unknown candidate"}
        description={
          [candidate.current_role, candidate.location].filter(Boolean).join(" · ") || undefined
        }
      />

      {/* ── Summary card ───────────────────────────────────────────────── */}
      <Card className="mb-5">
        <CardBody className="flex flex-col gap-6 sm:flex-row sm:items-center">
          <ScoreRing score={cred?.overall ?? 0} />

          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <VerdictStamp verdict={verdict} />
              {cred?.confidence && (
                <Badge tone="neutral">Confidence: {cred.confidence}</Badge>
              )}
              {cred?.recommendation_adjusted_by_verification && (
                <Badge tone="info" icon={<ShieldCheck className="size-3" />}>
                  Adjusted by verification
                </Badge>
              )}
            </div>

            <p className="text-sm leading-relaxed text-content-muted">
              {report.one_liner || verdictHint(verdict)}
            </p>

            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-content-faint">
              {candidate.email && (
                <a href={`mailto:${candidate.email}`} className="flex items-center gap-1.5 hover:text-content-muted">
                  <Mail aria-hidden className="size-3.5" />
                  {candidate.email}
                </a>
              )}
              {candidate.location && (
                <span className="flex items-center gap-1.5">
                  <MapPin aria-hidden className="size-3.5" />
                  {candidate.location}
                </span>
              )}
              {candidate.github && (
                <a
                  href={candidate.github}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="flex items-center gap-1.5 hover:text-content-muted"
                >
                  <Github aria-hidden className="size-3.5" />
                  GitHub
                </a>
              )}
              {candidate.linkedin && (
                <a
                  href={candidate.linkedin}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="flex items-center gap-1.5 hover:text-content-muted"
                >
                  <Linkedin aria-hidden className="size-3.5" />
                  LinkedIn
                </a>
              )}
              {report.created_at && (
                <span>Analysed {absoluteTime(report.created_at)}</span>
              )}
            </div>
          </div>
        </CardBody>

        {cred?.recommendation_adjustment_reason && (
          <div className="border-t border-line-subtle px-5 py-3">
            <p className="text-xs leading-relaxed text-content-faint">
              <span className="font-medium text-info">Verification changed this verdict:</span>{" "}
              {cred.recommendation_adjustment_reason}
            </p>
          </div>
        )}
      </Card>

      <Tabs items={TABS} value={tab} onChange={setTab} className="mb-5" />

      {/* ── Overview ───────────────────────────────────────────────────── */}
      <TabPanel id="overview" active={tab === "overview"}>
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Credibility breakdown"
              description="Each dimension with the reasoning behind its score."
            />
            <CardBody className="divide-y divide-line-subtle py-0">
              {(Object.keys(SUB_SCORE_LABELS) as (keyof SubScores)[]).map((key) => (
                <ScoreBar
                  key={key}
                  label={SUB_SCORE_LABELS[key]}
                  score={scores?.[key] ?? 0}
                  rationale={rationale[key]}
                />
              ))}
            </CardBody>
          </Card>

          {report.summary && (
            <Card>
              <CardHeader title="Summary" />
              <CardBody>
                <p className="text-sm leading-relaxed text-content-muted">{report.summary}</p>
              </CardBody>
            </Card>
          )}

          {report.ai_content_analysis && (
            <AIContentPanel analysis={report.ai_content_analysis} />
          )}

          {report.career_trajectory && (
            <CareerTrajectoryPanel data={report.career_trajectory} />
          )}

          {report.positive_signals && report.positive_signals.length > 0 && (
            <Card>
              <CardHeader
                title="Strengths"
                action={<Badge tone="positive">{report.positive_signals.length}</Badge>}
              />
              <CardBody>
                <ul className="space-y-3">
                  {report.positive_signals.map((s, i) => (
                    <li key={i} className="flex gap-2.5">
                      <Sparkles aria-hidden className="mt-0.5 size-3.5 shrink-0 text-positive" />
                      <div>
                        <div className="text-sm font-medium text-content">{s.title}</div>
                        <p className="mt-0.5 text-sm leading-relaxed text-content-muted">
                          {s.description}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}
        </div>
      </TabPanel>

      {/* ── Flags ──────────────────────────────────────────────────────── */}
      <TabPanel id="flags" active={tab === "flags"}>
        <Card>
          <CardHeader
            title="Concerns raised"
            description="Each one quotes the resume text that triggered it. They are prompts to ask a question, not conclusions."
            action={<FlagSummary flags={flags} />}
          />
          <CardBody className="space-y-2.5">
            {flags.length === 0 ? (
              <EmptyState
                icon={<ShieldCheck className="size-5" />}
                title="No concerns raised"
                description="Nothing in this resume contradicted itself. That is not confirmation the claims are true — it means the text gave no reason to doubt them."
              />
            ) : (
              flags.map((f, i) => (
                <FlagCard key={i} flag={f} defaultOpen={i === 0 && f.severity === "high"} />
              ))
            )}
          </CardBody>
        </Card>
      </TabPanel>

      <TabPanel id="skills" active={tab === "skills"}>
        <SkillsTab skills={report.skills} />
      </TabPanel>

      <TabPanel id="timeline" active={tab === "timeline"}>
        <TimelineTab
          experience={report.experience ?? []}
          education={report.education ?? []}
          projects={report.projects ?? []}
          certifications={report.certifications ?? []}
          gaps={report.timeline_gaps ?? []}
        />
      </TabPanel>

      <TabPanel id="verify" active={tab === "verify"}>
        <VerifyPanel
          verification={verification}
          loading={verifyLoading}
          error={verifyError}
          githubOverride={githubOverride}
          onGithubOverrideChange={setGithubOverride}
          onRun={runVerification}
        />
      </TabPanel>

      <TabPanel id="questions" active={tab === "questions"}>
        <QuestionsTab questions={report.interview_questions ?? []} />
      </TabPanel>

      <TabPanel id="copilot" active={tab === "copilot"}>
        <CopilotPanel
          scorecard={scorecard}
          onScorecardChange={setScorecard}
          questions={copilotQuestions}
          onQuestionsChange={setCopilotQuestions}
          newQuestion={newProbeQuestion}
          onNewQuestionChange={setNewProbeQuestion}
          notes={interviewNotes}
          onNotesChange={setInterviewNotes}
          saving={copilotSaving}
          success={copilotSuccess}
          error={copilotError}
          onSave={saveCopilotData}
        />
      </TabPanel>

      <TabPanel id="discuss" active={tab === "discuss"}>
        <DiscussPanel
          loading={discussLoading}
          error={discussError}
          comments={comments}
          votes={votesResult}
          teams={myTeams}
          sharedTeamId={report.team_id}
          sharing={sharing}
          newComment={newComment}
          posting={postingComment}
          currentUserId={user?.id}
          currentUserName={user?.full_name || user?.email}
          onNewCommentChange={setNewComment}
          onPostComment={postComment}
          onDeleteComment={removeComment}
          onVote={castVote}
          onShare={shareWithTeam}
        />
      </TabPanel>

      {/* ── Decision bar ───────────────────────────────────────────────── */}
      <Card className="mt-6">
        <CardHeader
          title="Your decision"
          description="Recorded against this candidate's file. It does not change the score or feed back into the model."
        />
        <CardBody className="space-y-4">
          {decisionError && <Alert tone="error">{decisionError}</Alert>}

          <div className="flex flex-wrap gap-2">
            {DECISIONS.map(({ value, label, icon: Icon, tone }) => {
              const active = decision === value;
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={active}
                  onClick={() => submitDecision(value)}
                  className={cn(
                    "flex items-center gap-2 rounded-md border px-3.5 py-2 text-sm font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:shadow-focus",
                    active
                      ? tone
                      : "border-line-strong bg-canvas-overlay text-content-muted hover:text-content",
                  )}
                >
                  <Icon aria-hidden className="size-4" />
                  {label}
                </button>
              );
            })}
          </div>

          {decision && (
            <div className="space-y-3 border-t border-line-subtle pt-4">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  icon={<Send className="size-3.5" />}
                  loading={notifyState === "sending"}
                  onClick={sendDefaultNotification}
                >
                  Email the candidate
                </Button>
                <Button
                  size="sm"
                  icon={<Pencil className="size-3.5" />}
                  loading={notifyDraftLoading}
                  onClick={openNotifyEditor}
                >
                  Edit first
                </Button>
              </div>

              {notifyMessage && (
                <Alert
                  tone={notifyState === "sent" ? "success" : "error"}
                  onDismiss={() => setNotifyMessage(null)}
                >
                  {notifyMessage}
                </Alert>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* ── Email editor ───────────────────────────────────────────────── */}
      {notifyEditorOpen && notifyDraft && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="notify-title"
          className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/70 p-5 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setNotifyEditorOpen(false);
          }}
        >
          <Card className="w-full max-w-lg animate-fade-in">
            <CardHeader
              title={<span id="notify-title">Email the candidate</span>}
              description={
                notifyDraft.candidate_email
                  ? `To: ${notifyDraft.candidate_email}`
                  : "No email was found on this resume."
              }
            />
            <CardBody className="space-y-4">
              <Input
                label="Subject"
                value={notifyDraft.subject}
                onChange={(e) =>
                  setNotifyDraft({ ...notifyDraft, subject: e.target.value })
                }
              />
              <Textarea
                label="Message"
                rows={10}
                value={notifyDraft.body}
                onChange={(e) => setNotifyDraft({ ...notifyDraft, body: e.target.value })}
              />
              <p className="text-xs leading-relaxed text-content-faint">
                This email goes directly to the candidate. Never paste credibility
                scores, flags or verification results into it — they are internal
                decision-support signals, not findings to share.
              </p>
              <div className="flex justify-end gap-2.5">
                <Button onClick={() => setNotifyEditorOpen(false)}>Cancel</Button>
                <Button
                  variant="primary"
                  loading={notifyState === "sending"}
                  disabled={!notifyDraft.has_email}
                  icon={<Send className="size-4" />}
                  onClick={sendEditedNotification}
                >
                  Send
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>
      )}
    </AppShell>
  );
}

export default function ReportPage() {
  return (
    <RequireAuth>
      <ReportContent />
    </RequireAuth>
  );
}
