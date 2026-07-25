"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { teamsAPI, APIError } from "@/lib/api";
import type { Team, TeamMember } from "@/types";

function roleBadge(role: string) {
  const m: Record<string, { label: string; color: string }> = {
    owner: { label: "Owner", color: "#D4AC5C" },
    admin: { label: "Admin", color: "#6E90AC" },
    member: { label: "Member", color: "#9C9483" },
  };
  return m[role] || m.member;
}

export default function TeamsPage() {
  const router = useRouter();
  const { token, hasHydrated } = useAuthStore();
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTeamName, setNewTeamName] = useState("");
  const [creating, setCreating] = useState(false);

  const [selected, setSelected] = useState<Team | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteStatus, setInviteStatus] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    if (hasHydrated && !token) router.replace("/login");
  }, [hasHydrated, token, router]);

  const loadTeams = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await teamsAPI.list(token);
      setTeams(res.teams);
    } catch (e) {
      if (e instanceof APIError && e.status === 503) {
        setError("Team collaboration isn't set up on this server yet — ask your admin to configure the database.");
      } else {
        setError("Could not load teams.");
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { loadTeams(); }, [loadTeams]);

  const loadMembers = useCallback(async (team: Team) => {
    if (!token) return;
    setSelected(team);
    setMembersLoading(true);
    setInviteStatus(null);
    try {
      const res = await teamsAPI.members(team.id, token);
      setMembers(res.members);
    } catch {
      setMembers([]);
    } finally {
      setMembersLoading(false);
    }
  }, [token]);

  const createTeam = async () => {
    if (!token || !newTeamName.trim()) return;
    setCreating(true);
    try {
      const team = await teamsAPI.create(newTeamName.trim(), token);
      setNewTeamName("");
      setTeams((prev) => [...prev, team]);
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not create team.");
    } finally {
      setCreating(false);
    }
  };

  const sendInvite = async () => {
    if (!token || !selected || !inviteEmail.trim()) return;
    setInviting(true);
    setInviteStatus(null);
    try {
      const res = await teamsAPI.invite(selected.id, inviteEmail.trim(), token);
      setInviteStatus(
        res.status === "already_invited"
          ? "Already invited — they'll join automatically next time they log in."
          : `Invited ${inviteEmail}. They'll join automatically the next time they log in or sign up with that email.`
      );
      setInviteEmail("");
    } catch (e) {
      setInviteStatus(e instanceof APIError ? e.message : "Could not send invite.");
    } finally {
      setInviting(false);
    }
  };

  const removeMember = async (userId: string) => {
    if (!token || !selected) return;
    try {
      await teamsAPI.removeMember(selected.id, userId, token);
      setMembers((prev) => prev.filter((m) => m.user_id !== userId));
    } catch (e) {
      setInviteStatus(e instanceof APIError ? e.message : "Could not remove member.");
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0D0C0A" }}>
      <nav style={{ height: 54, borderBottom: "1px solid #2A251C", display: "flex", alignItems: "center", paddingInline: 24, gap: 16, position: "sticky", top: 0, background: "rgba(13,12,10,.92)", backdropFilter: "blur(14px)", zIndex: 100 }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#3E5C76,#6E90AC)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>🔎</div>
          <span style={{ fontWeight: 900, fontSize: 15, color: "#EDE6D6", letterSpacing: -.4 }}>HireLens</span>
        </Link>
        <span style={{ color: "#2A251C" }}>|</span>
        <span style={{ fontSize: 13, color: "#9C9483" }}>Teams</span>
      </nav>

      <div style={{ maxWidth: 880, margin: "0 auto", padding: "32px 20px 80px" }}>
        <h1 className="font-display" style={{ fontSize: 24, fontWeight: 600, color: "#EDE6D6", marginBottom: 6 }}>Teams</h1>
        <p style={{ fontSize: 13, color: "#9C9483", marginBottom: 24 }}>
          Share candidate reports with teammates, comment, and vote together instead of screening solo.
        </p>

        {error && (
          <div style={{ padding: "12px 16px", background: "rgba(177,66,38,.08)", border: "1px solid rgba(177,66,38,.3)", borderRadius: 6, fontSize: 13, color: "#D46A4C", marginBottom: 20 }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          {/* Left: team list + create */}
          <div style={{ flex: "1 1 280px" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
              <input
                value={newTeamName}
                onChange={(e) => setNewTeamName(e.target.value)}
                placeholder="New team name"
                style={{ flex: 1, padding: "9px 12px", background: "#131110", border: "1px solid #2A251C", borderRadius: 6, color: "#EDE6D6", fontSize: 13, fontFamily: "inherit", outline: "none" }}
              />
              <button
                onClick={createTeam}
                disabled={creating || !newTeamName.trim()}
                style={{ padding: "9px 16px", borderRadius: 6, border: "none", background: "#3E5C76", color: "#EDE6D6", fontSize: 13, fontWeight: 700, cursor: "pointer", opacity: creating ? 0.6 : 1, whiteSpace: "nowrap" }}
              >
                + Create
              </button>
            </div>

            {loading ? (
              <div style={{ fontSize: 13, color: "#6B6355" }}>Loading…</div>
            ) : teams.length === 0 ? (
              <div style={{ fontSize: 13, color: "#6B6355" }}>No teams yet — create one to start collaborating.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {teams.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => loadMembers(t)}
                    style={{
                      textAlign: "left", padding: "12px 14px", borderRadius: 6, cursor: "pointer",
                      border: `1px solid ${selected?.id === t.id ? "#6E90AC" : "#2A251C"}`,
                      background: selected?.id === t.id ? "rgba(62,92,118,.1)" : "#131110",
                      fontFamily: "inherit",
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#EDE6D6" }}>{t.name}</div>
                    {t.my_role && <div style={{ fontSize: 10, color: roleBadge(t.my_role).color, marginTop: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>{roleBadge(t.my_role).label}</div>}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Right: selected team members + invite */}
          <div style={{ flex: "2 1 400px" }}>
            {!selected ? (
              <div style={{ padding: 40, textAlign: "center", border: "1px dashed #2A251C", borderRadius: 6, color: "#6B6355", fontSize: 13 }}>
                Select a team to view members and invite teammates.
              </div>
            ) : (
              <div style={{ background: "#17140F", border: "1px solid #2A251C", borderRadius: 6, padding: "18px 20px" }}>
                <div className="font-display" style={{ fontSize: 16, fontWeight: 600, color: "#EDE6D6", marginBottom: 14 }}>{selected.name}</div>

                {(selected.my_role === "owner" || selected.my_role === "admin") && (
                  <div style={{ marginBottom: 18 }}>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        placeholder="teammate@company.com"
                        style={{ flex: 1, padding: "9px 12px", background: "#131110", border: "1px solid #2A251C", borderRadius: 6, color: "#EDE6D6", fontSize: 13, fontFamily: "inherit", outline: "none" }}
                      />
                      <button
                        onClick={sendInvite}
                        disabled={inviting || !inviteEmail.trim()}
                        style={{ padding: "9px 16px", borderRadius: 6, border: "1px solid #2A251C", background: "#131110", color: "#D9D2C0", fontSize: 13, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}
                      >
                        Invite
                      </button>
                    </div>
                    {inviteStatus && <div style={{ fontSize: 12, color: "#9C9483", marginTop: 8, lineHeight: 1.6 }}>{inviteStatus}</div>}
                  </div>
                )}

                <div style={{ fontSize: 10, color: "#6B6355", letterSpacing: 1, textTransform: "uppercase", marginBottom: 8 }}>Members</div>
                {membersLoading ? (
                  <div style={{ fontSize: 13, color: "#6B6355" }}>Loading…</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {members.map((m) => (
                      <div key={m.user_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", background: "#131110", borderRadius: 6 }}>
                        <span style={{ fontSize: 12, color: "#D9D2C0", fontFamily: "monospace" }}>{m.user_id.slice(0, 8)}…</span>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <span style={{ fontSize: 11, color: roleBadge(m.role).color, textTransform: "uppercase", letterSpacing: 0.5 }}>{roleBadge(m.role).label}</span>
                          {(selected.my_role === "owner" || selected.my_role === "admin") && m.role !== "owner" && (
                            <button onClick={() => removeMember(m.user_id)} style={{ background: "none", border: "none", color: "#D46A4C", cursor: "pointer", fontSize: 12 }}>Remove</button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
