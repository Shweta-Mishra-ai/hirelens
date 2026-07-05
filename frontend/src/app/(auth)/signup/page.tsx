"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";

export default function SignupPage() {
  const router = useRouter();
  const { signup, isLoading, error, clearError, requiresEmailConfirmation } = useAuthStore();
  const [form, setForm] = useState({ email: "", password: "", fullName: "", company: "" });

  function setF(k: string, v: string) { setForm((p) => ({ ...p, [k]: v })); }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    clearError();
    try {
      const result = await signup(form.email, form.password, form.fullName, form.company || undefined);
      if (!result.requiresEmailConfirmation) router.replace("/dashboard");
    } catch { /* shown via store */ }
  }

  if (requiresEmailConfirmation) {
    return (
      <div style={{ minHeight: "100vh", background: "#060F1A", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
        <div style={{ background: "#0E1C2E", border: "1px solid #172840", borderRadius: 18, padding: "40px 32px", textAlign: "center", maxWidth: 420, width: "100%" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📧</div>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#EFF6FF", marginBottom: 12 }}>Check your email</h2>
          <p style={{ color: "#94A3B8", fontSize: 14, lineHeight: 1.7, marginBottom: 24 }}>
            We sent a confirmation link to <strong style={{ color: "#EFF6FF" }}>{form.email}</strong>. Click it, then log in.
          </p>
          <Link href="/login" style={{ display: "block", padding: "12px", borderRadius: 11, background: "linear-gradient(135deg,#1D6AFF,#1045C8)", color: "#EFF6FF", fontWeight: 700, fontSize: 14, textDecoration: "none" }}>
            Go to Login
          </Link>
        </div>
      </div>
    );
  }

  const S = {
    page: { minHeight: "100vh", background: "#060F1A", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 },
    card: { background: "#0E1C2E", border: "1px solid #172840", borderRadius: 18, padding: "32px 28px" },
    inp: { width: "100%", padding: "11px 14px", background: "#0A1525", border: "1px solid #172840", borderRadius: 10, color: "#EFF6FF", fontSize: 14, outline: "none", fontFamily: "inherit", boxSizing: "border-box" as const },
    lbl: { display: "block", fontSize: 11, fontWeight: 700, color: "#64748B", marginBottom: 6, letterSpacing: 1 },
    btn: { width: "100%", padding: "12px", borderRadius: 11, background: "linear-gradient(135deg,#1D6AFF,#1045C8)", border: "none", color: "#EFF6FF", fontWeight: 700, fontSize: 14, cursor: "pointer", fontFamily: "inherit", marginTop: 4 },
  };

  return (
    <div style={S.page as React.CSSProperties}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{ width: 38, height: 38, borderRadius: 11, background: "linear-gradient(135deg,#1D6AFF,#06B6D4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>🔎</div>
            <span style={{ fontSize: 22, fontWeight: 900, color: "#EFF6FF", letterSpacing: -1 }}>HireLens</span>
          </div>
        </div>
        <div style={S.card}>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: "#EFF6FF", margin: "0 0 24px" }}>Create account</h1>
          {error && <div style={{ padding: "12px 14px", background: "rgba(220,38,38,0.1)", border: "1px solid rgba(220,38,38,0.3)", borderRadius: 10, color: "#F87171", fontSize: 13, marginBottom: 20 }}>{error}</div>}
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {([
              ["FULL NAME", "fullName", "text", "Priya Sharma", true],
              ["WORK EMAIL", "email", "email", "priya@company.com", true],
              ["COMPANY (OPTIONAL)", "company", "text", "Acme Corp", false],
              ["PASSWORD (MIN 8 CHARS)", "password", "password", "••••••••", true],
            ] as [string, string, string, string, boolean][]).map(([lbl, key, type, ph, req]) => (
              <div key={key}>
                <label style={S.lbl as React.CSSProperties}>{lbl}</label>
                <input type={type} required={req} value={form[key as keyof typeof form]} onChange={e => setF(key, e.target.value)} placeholder={ph} style={S.inp} />
              </div>
            ))}
            <button type="submit" disabled={isLoading} style={{ ...S.btn, background: isLoading ? "#172840" : "linear-gradient(135deg,#1D6AFF,#1045C8)", cursor: isLoading ? "not-allowed" : "pointer", color: isLoading ? "#475569" : "#EFF6FF" }}>
              {isLoading ? "Creating account…" : "Create Account"}
            </button>
          </form>
          <p style={{ textAlign: "center", fontSize: 13, color: "#64748B", marginTop: 20 }}>
            Already have an account? <Link href="/login" style={{ color: "#4B8DFF", textDecoration: "none", fontWeight: 600 }}>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
