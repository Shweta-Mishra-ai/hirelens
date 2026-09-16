"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Users, Copy, Check, UserPlus, Plus, Link2 } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { teamsAPI, APIError } from "@/lib/api";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Field";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Feedback";
import { relativeTime, initials, pluralize } from "@/lib/format";
import { PersonAvatar, personLabel } from "@/components/ui/Person";
import { cn } from "@/lib/cn";
import type { Team, TeamMember } from "@/types";

const ROLE_TONE = {
  owner: "brand",
  admin: "info",
  member: "neutral",
} as const;

function InviteLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied (insecure context, permissions).
      // The input below is selectable, so the link is still usable.
      setCopied(false);
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-line bg-canvas-inset p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-content-muted">
        <Link2 aria-hidden className="size-3.5" />
        Shareable invite link
      </div>
      <div className="flex gap-2">
        <input
          readOnly
          value={url}
          onFocus={(e) => e.currentTarget.select()}
          aria-label="Invite link"
          className="min-w-0 flex-1 rounded-md border border-line-strong bg-canvas px-2.5 py-1.5 font-mono text-xs text-content-muted focus:outline-none focus:shadow-focus"
        />
        <Button
          size="sm"
          onClick={copy}
          icon={copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

function TeamsContent() {
  const router = useRouter();
  const { user, token, logout } = useAuthStore();

  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newTeamName, setNewTeamName] = useState("");
  const [creating, setCreating] = useState(false);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviting, setInviting] = useState(false);
  const [inviteMsg, setInviteMsg] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  const selectedTeam = teams.find((t) => t.id === selectedId) ?? null;

  // Note: this deliberately does NOT depend on the selected team. The previous
  // version did, which meant selecting a team re-ran the effect and refetched
  // the entire team list on every click.
  const loadTeams = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await teamsAPI.list(token);
      setTeams(res.teams);
      setSelectedId((prev) => prev ?? res.teams[0]?.id ?? null);
    } catch (e) {
      if (e instanceof APIError && e.status === 401) {
        logout();
        router.replace("/login");
        return;
      }
      setError(e instanceof APIError ? e.message : "Could not load your teams.");
    } finally {
      setLoading(false);
    }
  }, [token, logout, router]);

  useEffect(() => {
    void loadTeams();
  }, [loadTeams]);

  const loadMembers = useCallback(async () => {
    if (!token || !selectedId) {
      setMembers([]);
      return;
    }
    setMembersLoading(true);
    try {
      const res = await teamsAPI.members(selectedId, token);
      setMembers(res.members);
    } catch {
      setMembers([]);
    } finally {
      setMembersLoading(false);
    }
  }, [token, selectedId]);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !newTeamName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const team = await teamsAPI.create(newTeamName.trim(), token);
      setNewTeamName("");
      setTeams((prev) => [...prev, team]);
      setSelectedId(team.id);
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not create the team.");
    } finally {
      setCreating(false);
    }
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !selectedId || !inviteEmail.trim()) return;
    setInviting(true);
    setInviteMsg(null);
    setInviteUrl(null);
    setError(null);
    try {
      const res = await teamsAPI.invite(selectedId, inviteEmail.trim(), token);
      if (res.status === "already_invited") {
        setInviteMsg(`${inviteEmail.trim()} has already been invited.`);
      } else if (res.email_sent) {
        setInviteMsg(`Invitation emailed to ${inviteEmail.trim()}.`);
      } else {
        // No email service configured — the link is the only way through,
        // so say that plainly rather than implying an email went out.
        setInviteMsg(
          `Invite created for ${inviteEmail.trim()}. No email was sent — share the link below.`,
        );
      }
      if (res.invite_url) setInviteUrl(res.invite_url);
      setInviteEmail("");
      void loadMembers();
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not send the invite.");
    } finally {
      setInviting(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        title="Teams"
        description="Share candidate files with your hiring panel, and keep everyone's notes and decisions in one place."
      />

      {error && (
        <Alert tone="error" className="mb-5" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
        {/* Team list + create */}
        <div className="space-y-4">
          <Card>
            <CardHeader title="Your teams" />
            {loading ? (
              <CardBody className="space-y-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
              </CardBody>
            ) : teams.length === 0 ? (
              <CardBody>
                <p className="text-sm text-content-faint">
                  You&apos;re not in a team yet. Create one below.
                </p>
              </CardBody>
            ) : (
              <ul className="divide-y divide-line-subtle">
                {teams.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(t.id)}
                      aria-current={t.id === selectedId ? "true" : undefined}
                      className={cn(
                        "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors",
                        "focus-visible:outline-none focus-visible:bg-canvas-overlay",
                        t.id === selectedId
                          ? "bg-canvas-overlay"
                          : "hover:bg-canvas-overlay/50",
                      )}
                    >
                      <span
                        aria-hidden
                        className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas-inset text-2xs font-semibold text-content-muted"
                      >
                        {initials(t.name)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-content">
                          {t.name}
                        </span>
                        <span className="block text-xs text-content-faint">
                          Created {relativeTime(t.created_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Create a team" />
            <CardBody>
              <form onSubmit={handleCreate} className="space-y-3">
                <Input
                  value={newTeamName}
                  onChange={(e) => setNewTeamName(e.target.value)}
                  placeholder="e.g. Platform Hiring"
                  aria-label="Team name"
                  maxLength={80}
                />
                <Button
                  type="submit"
                  variant="primary"
                  fullWidth
                  loading={creating}
                  disabled={!newTeamName.trim()}
                  icon={<Plus className="size-4" />}
                >
                  Create team
                </Button>
              </form>
            </CardBody>
          </Card>
        </div>

        {/* Selected team detail */}
        {selectedTeam ? (
          <div className="space-y-5">
            <Card>
              <CardHeader
                title={selectedTeam.name}
                description={
                  selectedTeam.my_role
                    ? `You are ${selectedTeam.my_role === "owner" ? "the owner" : `a ${selectedTeam.my_role}`}`
                    : undefined
                }
                action={
                  <Badge tone="neutral">
                    {membersLoading ? "…" : pluralize(members.length, "member")}
                  </Badge>
                }
              />
              <CardBody>
                {membersLoading ? (
                  <div className="space-y-2">
                    <Skeleton className="h-9" />
                    <Skeleton className="h-9" />
                  </div>
                ) : members.length === 0 ? (
                  <p className="text-sm text-content-faint">
                    No members listed yet.
                  </p>
                ) : (
                  <ul className="divide-y divide-line-subtle">
                    {members.map((m) => (
                      <li key={m.user_id} className="flex items-center gap-3 py-2.5">
                        <PersonAvatar
                          name={m.user_name}
                          avatarName={(m.is_me ?? m.user_id === user?.id) ? (user?.full_name || user?.email) : undefined}
                          size="sm"
                        />
                        <span className="min-w-0 flex-1 truncate text-sm text-content-muted">
                          {personLabel(m.user_name)}
                        </span>
                        <Badge tone={ROLE_TONE[m.role] ?? "neutral"} className="capitalize">
                          {m.role}
                        </Badge>
                        <span className="hidden w-20 text-right text-xs text-content-faint sm:block">
                          {relativeTime(m.joined_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Invite a teammate"
                description="They'll join automatically the next time they sign in."
              />
              <CardBody>
                <form onSubmit={handleInvite} className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[14rem] flex-1">
                    <Input
                      type="email"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      placeholder="teammate@company.com"
                      aria-label="Teammate email"
                    />
                  </div>
                  <Button
                    type="submit"
                    variant="primary"
                    loading={inviting}
                    disabled={!inviteEmail.trim()}
                    icon={<UserPlus className="size-4" />}
                  >
                    Send invite
                  </Button>
                </form>

                {inviteMsg && (
                  <Alert tone="success" className="mt-3">
                    {inviteMsg}
                  </Alert>
                )}
                {inviteUrl && <InviteLink url={inviteUrl} />}
              </CardBody>
            </Card>
          </div>
        ) : (
          <Card>
            <EmptyState
              icon={<Users className="size-5" />}
              title={loading ? "Loading teams…" : "No team selected"}
              description={
                loading
                  ? undefined
                  : "Create a team to share candidate files, leave notes and record decisions together."
              }
            />
          </Card>
        )}
      </div>
    </AppShell>
  );
}

export default function TeamsPage() {
  return (
    <RequireAuth>
      <TeamsContent />
    </RequireAuth>
  );
}
