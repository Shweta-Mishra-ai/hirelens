"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { teamsAPI, APIError } from "@/lib/api";
import {
  AlertCircle,
  Copy,
  User as UserIcon,
  Check,
} from "lucide-react";
import type { Team, TeamMember } from "@/types";
import { color, gradient, radius } from "@/lib/design-tokens";
import { Card, Button, TextInput, AlertBanner, PageShell } from "@/components/ui/primitives";
import { AppNavbar } from "@/components/ui/AppNavbar";

export default function TeamsPage() {
  const router = useRouter();
  const { user, token, logout, sessionChecked } = useAuthStore();
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newTeamName, setNewTeamName] = useState("");
  const [creating, setCreating] = useState(false);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviting, setInviting] = useState(false);
  const [inviteSuccess, setInviteSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (sessionChecked && !token) router.replace("/login");
  }, [sessionChecked, token, router]);

  const loadTeams = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await teamsAPI.list(token);
      setTeams(res.teams);
      if (res.teams.length > 0 && !selectedTeam) {
        setSelectedTeam(res.teams[0]);
      }
    } catch (e) {
      if (e instanceof APIError && e.status === 401) {
        logout(); router.replace("/login");
      } else {
        setError("Could not load teams.");
      }
    } finally {
      setLoading(false);
    }
  }, [token, logout, router, selectedTeam]);

  useEffect(() => { loadTeams(); }, [loadTeams]);

  const loadMembers = useCallback(async () => {
    if (!token || !selectedTeam) return;
    try {
      const res = await teamsAPI.members(selectedTeam.id, token);
      setMembers(res.members);
    } catch (e) {
      console.warn("Could not load team members:", e);
    }
  }, [token, selectedTeam]);

  useEffect(() => { loadMembers(); }, [loadMembers]);

  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newTeamName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const newTeam = await teamsAPI.create(newTeamName.trim(), token);
      setNewTeamName("");
      setTeams(prev => [...prev, newTeam]);
      setSelectedTeam(newTeam);
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not create team.");
    } finally {
      setCreating(false);
    }
  };

  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !selectedTeam || !inviteEmail.trim()) return;
    setInviting(true);
    setInviteSuccess(null);
    setInviteUrl(null);
    setError(null);
    try {
      const res = await teamsAPI.invite(selectedTeam.id, inviteEmail.trim(), token);
      if (res.status === "already_invited") {
        setInviteSuccess(`User ${inviteEmail} is already invited.`);
      } else if (res.email_sent) {
        setInviteSuccess(`Invitation email successfully sent to ${inviteEmail}!`);
      } else {
        setInviteSuccess(`Invite created for ${inviteEmail}!`);
      }

      if (res.invite_url) {
        setInviteUrl(res.invite_url);
      }

      setInviteEmail("");
      loadMembers();
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not send invite.");
    } finally {
      setInviting(false);
    }
  };

  return (
    <PageShell>
      <AppNavbar />

      {/* Main Container */}
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "36px 24px 80px" }}>

        <div style={{ marginBottom: 32 }}>
          <h1 className="font-display" style={{ fontSize: 28, fontWeight: 600, color: color.textPrimary, margin: "0 0 8px" }}>
            Team Collaboration & Workspaces
          </h1>
          <p style={{ fontSize: 14, color: color.textMuted, margin: 0 }}>
            Collaborate with fellow recruiters, share candidate evaluation reports, and vote on hiring decisions together.
          </p>
        </div>

        {error && (
          <div style={{ marginBottom: 24 }}>
            <AlertBanner tone="danger" icon={<AlertCircle size={15} />}>{error}</AlertBanner>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 24 }}>

          {/* Left Column: Create Team & Team List */}
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Create Team Card */}
            <Card style={{ padding: 20 }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary, marginBottom: 12 }}>+ Create New Team</div>
              <form onSubmit={handleCreateTeam} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <TextInput
                  type="text"
                  value={newTeamName}
                  onChange={e => setNewTeamName(e.target.value)}
                  placeholder="Team Name (e.g. Engineering Hiring)"
                />
                <Button type="submit" disabled={creating || !newTeamName.trim()}>
                  {creating ? "Creating…" : "Create Team Workspace"}
                </Button>
              </form>
            </Card>

            {/* Teams List */}
            <Card style={{ padding: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: color.textSecondary, marginBottom: 12 }}>Your Teams ({teams.length})</div>
              {loading && <div style={{ fontSize: 13, color: color.textMuted }}>Loading teams…</div>}
              {!loading && teams.length === 0 && (
                <div style={{ fontSize: 13, color: color.textMuted }}>No teams yet. Create one above to start collaborating!</div>
              )}
              {!loading && teams.map(t => (
                <div key={t.id} onClick={() => setSelectedTeam(t)} style={{
                  padding: "12px 14px", borderRadius: radius.md,
                  background: selectedTeam?.id === t.id ? color.surfaceRaised : "transparent",
                  border: `1px solid ${selectedTeam?.id === t.id ? color.brand : color.borderSubtle}`,
                  cursor: "pointer", marginBottom: 8, transition: "all 0.15s ease",
                }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>{t.name}</div>
                  <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>Role: {t.my_role || "member"}</div>
                </div>
              ))}
            </Card>

          </div>

          {/* Right Column: Selected Team Details & Members */}
          <Card style={{ padding: 28 }}>
            {selectedTeam ? (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
                  <div>
                    <h2 className="font-display" style={{ margin: 0, fontSize: 21, fontWeight: 600, color: color.textPrimary }}>{selectedTeam.name}</h2>
                    <span style={{ fontSize: 12, color: color.brandLight, fontWeight: 600 }}>Your Role: {selectedTeam.my_role || "Owner"}</span>
                  </div>
                </div>

                {/* Invite Teammate */}
                <div style={{ background: color.bgAlt, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.lg, padding: 20, marginBottom: 24 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary, marginBottom: 8 }}>Invite Teammate</div>
                  <form onSubmit={handleInvite} style={{ display: "flex", gap: 10 }}>
                    <TextInput
                      type="email"
                      value={inviteEmail}
                      onChange={e => setInviteEmail(e.target.value)}
                      placeholder="colleague@company.com"
                      style={{ flex: 1 }}
                    />
                    <Button type="submit" disabled={inviting || !inviteEmail.trim()} style={{ whiteSpace: "nowrap" }}>
                      {inviting ? "Inviting…" : "Send Invite"}
                    </Button>
                  </form>
                  {inviteSuccess && (
                    <div style={{ fontSize: 13, color: color.success, marginTop: 10, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                      <Check size={14} />
                      <span>{inviteSuccess}</span>
                    </div>
                  )}
                  {inviteUrl && (
                    <div style={{ marginTop: 10, padding: "10px 12px", background: color.bgAlt, border: `1px solid ${color.border}`, borderRadius: radius.md, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                      <span style={{ fontSize: 11, color: color.textMuted, fontFamily: "var(--font-mono), monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{inviteUrl}</span>
                      <button onClick={() => { navigator.clipboard.writeText(inviteUrl); alert("Invitation link copied to clipboard!"); }} style={{ padding: "4px 10px", borderRadius: radius.sm, background: color.surfaceRaised, border: `1px solid ${color.border}`, color: color.brandLight, fontSize: 11, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6 }}>
                        <Copy size={12} />
                        <span>Copy Link</span>
                      </button>
                    </div>
                  )}
                </div>

                {/* Members List */}
                <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary, marginBottom: 12 }}>Team Members ({members.length})</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {members.map(m => (
                    <div key={m.user_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", background: color.bgAlt, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 30, height: 30, borderRadius: "50%", background: color.brand, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <UserIcon size={14} color="#FFF" />
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary }}>{m.user_id}</div>
                          <div style={{ fontSize: 11, color: color.textMuted }}>Joined: {new Date(m.joined_at).toLocaleDateString()}</div>
                        </div>
                      </div>
                      <span style={{ padding: "3px 10px", borderRadius: radius.sm, background: color.surfaceRaised, border: `1px solid ${color.border}`, color: color.brandLight, fontSize: 11, fontWeight: 600, textTransform: "capitalize" }}>
                        {m.role}
                      </span>
                    </div>
                  ))}
                </div>

              </div>
            ) : (
              <div style={{ padding: 48, textAlign: "center", color: color.textMuted }}>
                Select a team from the left or create a new team workspace.
              </div>
            )}
          </Card>

        </div>

      </div>
    </PageShell>
  );
}
