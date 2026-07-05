"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";

export default function LoginPage() {
  const router = useRouter();
  const { login, isLoading, error, clearError } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    clearError();
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch { /* shown via store */ }
  }

  const S = {
    page: { minHeight: "100vh", background: "#060F1A", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 },
    card: { background: "#0E1C2E", border: "1px solid #172840", borderRadius: 18, padding: "32px 28px", width: "100%", maxWidth: 420 },
    inp: { width: "100%", padding: "11px 14px", background: "#0A1525", border: "1px solid #172840", borderRadius: 10, color: "#EFF6FF", fontSize: 14, outline: "none", fontFamily: "inherit", boxSizing: "border-box" as const },
    lbl: { display: "block", fontSize: 11, fontWeight: 700, color: "#64748B", marginBottom: 6, letterSpacing: 1 },
  };

  return (
    <div style={S.page as React.CSSProperties}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{ width: 38, height: 38, borderRadius: 11, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>🔎</div>
            <span style={{ fontSize: 22, fontWeight: 900, color: "#EFF6FF", letterSpacing: -1 }}>HireLens</span>
          </div>
          <p style={{ color: "#94A3B8", fontSize: 14, margin: 0 }}>AI Recruiter Intelligence</p>
        </div>
        <div style={S.card}>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: "#EFF6FF", margin: "0 0 24px", letterSpacing: -.5 }}>Sign in</h1>
          {error && (
            <div style={{ padding: "12px 14px", background: "rgba(220,38,38,0.1)", border: "1px solid rgba(220,38,38,0.3)", borderRadius: 10, color: "#F87171", fontSize: 13, marginBottom: 20 }}>
              {error}
            </div>
          )}
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <label style={S.lbl as React.CSSProperties}>EMAIL</label>
              <input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="recruiter@company.com" style={S.inp} autoComplete="email" />
            </div>
            <div>
              <label style={S.lbl as React.CSSProperties}>PASSWORD</label>
              <input type="password" required value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" style={S.inp} autoComplete="current-password" />
            </div>
            <button type="submit" disabled={isLoading} style={{ width: "100%", padding: "12px", borderRadius: 11, background: isLoading ? "#172840" : "linear-gradient(135deg,#1D6AFF,#1045C8)", border: "none", color: isLoading ? "#475569" : "#EFF6FF", fontWeight: 700, fontSize: 14, cursor: isLoading ? "not-allowed" : "pointer", fontFamily: "inherit", marginTop: 4 }}>
              {isLoading ? "Signing in…" : "Sign In"}
            </button>
          </form>
          <p style={{ textAlign: "center", fontSize: 13, color: "#64748B", marginTop: 20, marginBottom: 0 }}>
            No account? <Link href="/signup" style={{ color: "#4B8DFF", textDecoration: "none", fontWeight: 600 }}>Create one free</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
