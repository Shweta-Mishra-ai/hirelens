"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { teamsAPI, APIError } from "@/lib/api";
import type { Team, TeamMember } from "@/types";

export default function TeamsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, token, logout, hasHydrated } = useAuthStore();
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
    if (hasHydrated && !token) router.replace("/login");
  }, [hasHydrated, token, router]);

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

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !selectedTeam || !inviteEmail.trim()) return;
    setInviting(true);
    setInviteSuccess(null);
    setError(null);
    try {
      const res = await teamsAPI.invite(selectedTeam.id, inviteEmail.trim(), token);
      setInviteSuccess(res.status === "already_invited" ? "User already invited." : `Invite sent to ${inviteEmail}!`);
      setInviteEmail("");
      loadMembers();
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not send invite.");
    } finally {
      setInviting(false);
    }
  };

  const NAV_LINKS = [
    { href: "/dashboard", label: "Dashboard", icon: "📊" },
    { href: "/analyze", label: "Analyze", icon: "⚡" },
    { href: "/bulk", label: "Bulk Upload", icon: "🗂️" },
    { href: "/match", label: "JD Match", icon: "🎯" },
    { href: "/teams", label: "Teams", icon: "👥" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#0B0F17", color: "#F8FAFC" }}>
      {/* Navbar */}
      <nav style={{
        height: 64, borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        display: "flex", alignItems: "center", paddingInline: 28, gap: 24,
        position: "sticky", top: 0, background: "rgba(11, 15, 23, 0.85)",
        backdropFilter: "blur(16px)", zIndex: 100
      }}>
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
          <div style={{
            width: 32, height: 32, borderRadius: 10,
            background: "linear-gradient(135deg, #6366F1, #8B5CF6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16, boxShadow: "0 0 16px rgba(99,102,241,0.4)"
          }}>🔎</div>
          <span style={{ fontWeight: 800, fontSize: 18, color: "#F8FAFC", letterSpacing: -0.5 }}>HireLens</span>
        </Link>

        {/* Tab Pills */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: "rgba(30, 41, 59, 0.5)", padding: 4, borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)" }}>
          {NAV_LINKS.map(link => {
            const active = pathname === link.href;
            return (
              <Link key={link.href} href={link.href} style={{
                padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                color: active ? "#F8FAFC" : "#94A3B8",
                background: active ? "rgba(99, 102, 241, 0.25)" : "transparent",
                border: active ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid transparent",
                textDecoration: "none", transition: "all 0.15s ease",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <span>{link.icon}</span>
                <span>{link.label}</span>
              </Link>
            );
          })}
        </div>

        <div style={{ flex: 1 }} />

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", borderRadius: 99, background: "rgba(30,41,59,0.6)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ width: 22, height: 22, borderRadius: "50%", background: "#6366F1", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>
              {user?.full_name ? user.full_name[0].toUpperCase() : "U"}
            </div>
            <span style={{ fontSize: 12, color: "#CBD5E1", fontWeight: 500 }}>{user?.email}</span>
          </div>
          <button onClick={() => { logout(); router.replace("/login"); }}
            style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(30,41,59,0.4)", color: "#94A3B8", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
            Sign Out
          </button>
        </div>
      </nav>

      {/* Main Container */}
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "36px 24px 80px" }}>
        
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 30, fontWeight: 800, color: "#F8FAFC", margin: "0 0 8px", letterSpacing: -0.7 }}>
            Team Collaboration & Workspaces
          </h1>
          <p style={{ fontSize: 14, color: "#94A3B8", margin: 0 }}>
            Collaborate with fellow recruiters, share candidate evaluation reports, and vote on hiring decisions together.
          </p>
        </div>

        {error && (
          <div style={{ padding: "12px 16px", borderRadius: 12, background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#EF4444", fontSize: 13, marginBottom: 24 }}>
            ⚠️ {error}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 24 }}>
          
          {/* Left Column: Create Team & Team List */}
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            
            {/* Create Team Card */}
            <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 20, padding: 20 }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#F8FAFC", marginBottom: 12 }}>+ Create New Team</div>
              <form onSubmit={handleCreateTeam} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <input
                  type="text"
                  value={newTeamName}
                  onChange={e => setNewTeamName(e.target.value)}
                  placeholder="Team Name (e.g. Engineering Hiring)"
                  style={{ padding: "10px 12px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }}
                />
                <button type="submit" disabled={creating || !newTeamName.trim()} style={{ padding: "10px", borderRadius: 10, background: "linear-gradient(135deg,#6366F1,#4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 13, border: "none", cursor: newTeamName.trim() ? "pointer" : "default", opacity: newTeamName.trim() ? 1 : 0.5 }}>
                  {creating ? "Creating…" : "Create Team Workspace"}
                </button>
              </form>
            </div>

            {/* Teams List */}
            <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 20, padding: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#CBD5E1", marginBottom: 12 }}>Your Teams ({teams.length})</div>
              {loading && <div style={{ fontSize: 13, color: "#94A3B8" }}>Loading teams…</div>}
              {!loading && teams.length === 0 && (
                <div style={{ fontSize: 13, color: "#94A3B8" }}>No teams yet. Create one above to start collaborating!</div>
              )}
              {!loading && teams.map(t => (
                <div key={t.id} onClick={() => setSelectedTeam(t)} style={{ padding: "12px 14px", borderRadius: 12, background: selectedTeam?.id === t.id ? "rgba(99,102,241,0.2)" : "rgba(15,23,42,0.4)", border: `1px solid ${selectedTeam?.id === t.id ? "rgba(99,102,241,0.4)" : "rgba(255,255,255,0.05)"}`, cursor: "pointer", marginBottom: 8, transition: "all 0.15s ease" }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC" }}>{t.name}</div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 2 }}>Role: {t.my_role || "member"}</div>
                </div>
              ))}
            </div>

          </div>

          {/* Right Column: Selected Team Details & Members */}
          <div style={{ background: "rgba(30, 41, 59, 0.6)", backdropFilter: "blur(16px)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 20, padding: 28 }}>
            {selectedTeam ? (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
                  <div>
                    <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#F8FAFC" }}>{selectedTeam.name}</h2>
                    <span style={{ fontSize: 12, color: "#818CF8", fontWeight: 600 }}>Your Role: {selectedTeam.my_role || "Owner"}</span>
                  </div>
                </div>

                {/* Invite Teammate */}
                <div style={{ background: "rgba(15,23,42,0.6)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 16, padding: 20, marginBottom: 24 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC", marginBottom: 8 }}>Invite Teammate</div>
                  <form onSubmit={handleInvite} style={{ display: "flex", gap: 10 }}>
                    <input
                      type="email"
                      value={inviteEmail}
                      onChange={e => setInviteEmail(e.target.value)}
                      placeholder="colleague@company.com"
                      style={{ flex: 1, padding: "10px 14px", background: "rgba(30,41,59,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }}
                    />
                    <button type="submit" disabled={inviting || !inviteEmail.trim()} style={{ padding: "10px 20px", borderRadius: 10, background: "linear-gradient(135deg,#6366F1,#4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 13, border: "none", cursor: "pointer" }}>
                      {inviting ? "Inviting…" : "Send Invite"}
                    </button>
                  </form>
                  {inviteSuccess && <div style={{ fontSize: 12, color: "#10B981", marginTop: 8 }}>✓ {inviteSuccess}</div>}
                </div>

                {/* Members List */}
                <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC", marginBottom: 12 }}>Team Members ({members.length})</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {members.map(m => (
                    <div key={m.user_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", background: "rgba(15,23,42,0.4)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: 12 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#6366F1", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>
                          👤
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: "#F8FAFC" }}>{m.user_id}</div>
                          <div style={{ fontSize: 11, color: "#94A3B8" }}>Joined: {new Date(m.joined_at).toLocaleDateString()}</div>
                        </div>
                      </div>
                      <span style={{ padding: "3px 10px", borderRadius: 99, background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)", color: "#818CF8", fontSize: 11, fontWeight: 600, textTransform: "capitalize" }}>
                        {m.role}
                      </span>
                    </div>
                  ))}
                </div>

              </div>
            ) : (
              <div style={{ padding: 48, textAlign: "center", color: "#94A3B8" }}>
                Select a team from the left or create a new team workspace.
              </div>
            )}
          </div>

        </div>

      </div>
    </div>
  );
}
