"use client";
import { MessageSquare, Send, Share2, ThumbsUp, ThumbsDown, Meh, Trash2 } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Textarea, Select } from "@/components/ui/Field";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Feedback";
import { relativeTime } from "@/lib/format";
import { PersonAvatar, personLabel } from "@/components/ui/Person";
import { cn } from "@/lib/cn";
import type { ReportComment, VotesResult, Team } from "@/types";

type Vote = "advance" | "maybe" | "reject";

const VOTE_META: Record<
  Vote,
  { label: string; icon: typeof ThumbsUp; active: string }
> = {
  advance: {
    label: "Advance",
    icon: ThumbsUp,
    active: "border-positive-line bg-positive-soft text-positive",
  },
  maybe: {
    label: "Maybe",
    icon: Meh,
    active: "border-caution-line bg-caution-soft text-caution",
  },
  reject: {
    label: "Not a match",
    icon: ThumbsDown,
    active: "border-critical-line bg-critical-soft text-critical",
  },
};

export function DiscussPanel({
  loading,
  error,
  comments,
  votes,
  teams,
  sharedTeamId,
  sharing,
  newComment,
  posting,
  currentUserId,
  currentUserName,
  onNewCommentChange,
  onPostComment,
  onDeleteComment,
  onVote,
  onShare,
}: {
  loading: boolean;
  error: string | null;
  comments: ReportComment[];
  votes: VotesResult | null;
  teams: Team[];
  sharedTeamId: string | null | undefined;
  sharing: boolean;
  newComment: string;
  posting: boolean;
  currentUserId: string | undefined;
  currentUserName?: string;
  onNewCommentChange: (v: string) => void;
  onPostComment: () => void;
  onDeleteComment: (id: string) => void;
  onVote: (v: Vote) => void;
  onShare: (teamId: string) => void;
}) {
  const sharedTeam = teams.find((t) => t.id === sharedTeamId);

  return (
    <div className="space-y-5">
      {error && <Alert tone="error">{error}</Alert>}

      <Card>
        <CardHeader
          title="Share with a team"
          description="Everyone on the team can then read this file, comment and vote."
          action={sharedTeam ? <Badge tone="brand">Shared with {sharedTeam.name}</Badge> : null}
        />
        <CardBody>
          {teams.length === 0 ? (
            <p className="text-sm text-content-faint">
              You&apos;re not in a team yet. Create one on the Teams page first.
            </p>
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[14rem] flex-1">
                <Select
                  label="Team"
                  value={sharedTeamId ?? ""}
                  disabled={sharing}
                  onChange={(e) => e.target.value && onShare(e.target.value)}
                  options={[
                    { value: "", label: "Select a team…" },
                    ...teams.map((t) => ({ value: t.id, label: t.name })),
                  ]}
                />
              </div>
              {sharing && (
                <span className="pb-2 text-xs text-content-faint">Sharing…</span>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Panel vote"
          description="A non-binding signal of where your team stands. It does not change the credibility score."
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(VOTE_META) as Vote[]).map((v) => {
              const meta = VOTE_META[v];
              const Icon = meta.icon;
              const active = votes?.my_vote === v;
              const count = votes?.tally[v] ?? 0;
              return (
                <button
                  key={v}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onVote(v)}
                  className={cn(
                    "flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:shadow-focus",
                    active
                      ? meta.active
                      : "border-line-strong bg-canvas-overlay text-content-muted hover:text-content",
                  )}
                >
                  <Icon aria-hidden className="size-3.5" />
                  {meta.label}
                  <span className="tabular text-xs opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
          {votes?.my_vote && (
            <p className="text-xs text-content-faint">
              Your vote: {VOTE_META[votes.my_vote].label}. Click it again to change it.
            </p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Discussion" />
        <CardBody className="space-y-4">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : comments.length === 0 ? (
            <EmptyState
              icon={<MessageSquare className="size-5" />}
              title="No comments yet"
              description="Leave a note for whoever picks this candidate up next."
              className="py-8"
            />
          ) : (
            <ul className="space-y-3">
              {comments.map((c) => (
                <li key={c.id} className="flex gap-3">
                  <PersonAvatar
                    name={c.user_name}
                    avatarName={(c.is_me ?? c.user_id === currentUserId) ? currentUserName : undefined}
                    size="sm"
                    className="mt-0.5"
                  />
                  <div className="min-w-0 flex-1 rounded-lg border border-line bg-canvas-inset px-3.5 py-2.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-xs font-medium text-content-muted">
                        {personLabel(c.user_name)}
                      </span>
                      <div className="flex shrink-0 items-center gap-2">
                        <time className="text-xs text-content-faint" dateTime={c.created_at}>
                          {relativeTime(c.created_at)}
                        </time>
                        {(c.is_me ?? c.user_id === currentUserId) && (
                          <button
                            type="button"
                            aria-label="Delete comment"
                            onClick={() => onDeleteComment(c.id)}
                            className="rounded p-0.5 text-content-faint transition-colors hover:text-critical"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-content-muted">
                      {c.comment}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-2.5 border-t border-line-subtle pt-4">
            <Textarea
              rows={3}
              value={newComment}
              onChange={(e) => onNewCommentChange(e.target.value)}
              placeholder="Add a note for your team…"
              aria-label="New comment"
            />
            <div className="flex justify-end">
              <Button
                variant="primary"
                size="sm"
                loading={posting}
                disabled={!newComment.trim()}
                icon={<Send className="size-3.5" />}
                onClick={onPostComment}
              >
                Post
              </Button>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
