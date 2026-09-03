"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const { token, hasHydrated, setAuth } = useAuthStore();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  // Auto-redirect if already logged in
  useEffect(() => {
    if (hasHydrated && token) {
      router.replace("/dashboard");
    }
  }, [hasHydrated, token, router]);

  // Forgot password modal state
  const [showForgotModal, setShowForgotModal] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);
  const [forgotMsg, setForgotMsg] = useState<string | null>(null);


  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authAPI.login(email.trim(), password);
      setAuth(res.access_token, res.user);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof APIError ? err.message : "Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  const handleDemoLogin = async () => {
    setEmail("demo@hirelens.ai");
    setPassword("Password123!");
    setLoading(true);
    setError(null);
    try {
      const res = await authAPI.login("demo@hirelens.ai", "Password123!");
      setAuth(res.access_token, res.user);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof APIError ? err.message : "Demo login failed. Make sure backend is running.");
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    const isConfigured =
      process.env.NEXT_PUBLIC_SUPABASE_URL &&
      !process.env.NEXT_PUBLIC_SUPABASE_URL.includes("placeholder");
    if (!isConfigured) {
      setError("Google OAuth requires Supabase to be configured in .env.local. Please use Email & Password or One-Click Demo Login.");
      return;
    }
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/dashboard` },
    });
    if (error) setError(error.message);
  };

  const handleForgotSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!forgotEmail.trim()) return;
    setForgotLoading(true);
    setForgotMsg(null);
    try {
      const res = await authAPI.forgotPassword(forgotEmail.trim());
      setForgotMsg(res.message);
    } catch (e) {
      setForgotMsg("Could not send password reset email. Try again later.");
    } finally {
      setForgotLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0B0F17", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div className="animate-fade-up" style={{
        width: "100%", maxWidth: 440,
        background: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(16px)",
        border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 24, padding: "40px 36px",
        boxShadow: "0 12px 40px -10px rgba(0,0,0,0.6)"
      }}>
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 28 }}>
          <div style={{
            width: 38, height: 38, borderRadius: 12,
            background: "linear-gradient(135deg, #6366F1, #8B5CF6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 20, boxShadow: "0 0 20px rgba(99,102,241,0.4)"
          }}>🔎</div>
          <span style={{ fontWeight: 800, fontSize: 24, color: "#F8FAFC", letterSpacing: -0.6 }}>HireLens</span>
        </div>

        <h1 style={{ fontSize: 22, fontWeight: 800, color: "#F8FAFC", textAlign: "center", margin: "0 0 6px" }}>Sign in to HireLens</h1>
        <p style={{ fontSize: 13, color: "#94A3B8", textAlign: "center", margin: "0 0 28px" }}>AI Candidate Credibility Intelligence</p>

        {error && (
          <div style={{ padding: "12px 14px", borderRadius: 10, background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#EF4444", fontSize: 13, marginBottom: 20 }}>
            ⚠️ {error}
          </div>
        )}

        {/* One-Click Demo Login */}
        <button
          type="button"
          onClick={handleDemoLogin}
          disabled={loading}
          style={{
            width: "100%", padding: "11px 16px", borderRadius: 12,
            border: "1px solid rgba(99, 102, 241, 0.4)",
            background: "linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.2))",
            color: "#C7D2FE", fontWeight: 700, fontSize: 13,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
            cursor: "pointer", marginBottom: 12, transition: "all 0.15s"
          }}
        >
          <span>⚡</span> {loading ? "Signing in…" : "One-Click Demo Login (demo@hirelens.ai)"}
        </button>

        {/* Google OAuth */}
        <button onClick={handleGoogleLogin} style={{
          width: "100%", padding: "11px 16px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.1)",
          background: "rgba(15, 23, 42, 0.6)", color: "#F8FAFC", fontWeight: 600, fontSize: 13,
          display: "flex", alignItems: "center", justifyContent: "center", gap: 10, cursor: "pointer", marginBottom: 20
        }}>
          <span>🌐</span> Sign in with Google
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.08)" }} />
          <span style={{ fontSize: 12, color: "#64748B" }}>or email</span>
          <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.08)" }} />
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#CBD5E1", marginBottom: 6 }}>Email address</label>
            <input
              type="email"
              required
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="recruiter@company.com"
              style={{ width: "100%", boxSizing: "border-box", padding: "11px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }}
            />
          </div>

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: "#CBD5E1" }}>Password</label>
              <button type="button" onClick={() => setShowForgotModal(true)} style={{ background: "none", border: "none", color: "#818CF8", fontSize: 12, cursor: "pointer", padding: 0 }}>
                Forgot password?
              </button>
            </div>
            <input
              type="password"
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{ width: "100%", boxSizing: "border-box", padding: "11px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }}
            />
          </div>

          <button type="submit" disabled={loading} style={{
            width: "100%", padding: "12px", borderRadius: 12, border: "none",
            background: "linear-gradient(135deg, #6366F1, #4F46E5)", color: "#FFFFFF",
            fontWeight: 700, fontSize: 14, cursor: "pointer", marginTop: 4
          }}>
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <div style={{ marginTop: 24, textAlign: "center", fontSize: 13, color: "#94A3B8" }}>
          Don&apos;t have an account?{" "}
          <Link href="/signup" style={{ color: "#818CF8", fontWeight: 600, textDecoration: "none" }}>Sign up</Link>
        </div>
      </div>

      {/* Forgot Password Modal */}
      {showForgotModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200, padding: 20 }}>
          <div style={{ width: "100%", maxWidth: 400, background: "#1E293B", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 20, padding: 28 }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 18, color: "#F8FAFC" }}>Reset Your Password</h3>
            <p style={{ margin: "0 0 20px", fontSize: 13, color: "#94A3B8" }}>Enter your registered email and we&apos;ll send reset instructions.</p>
            <form onSubmit={handleForgotSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <input
                type="email"
                required
                value={forgotEmail}
                onChange={e => setForgotEmail(e.target.value)}
                placeholder="recruiter@company.com"
                style={{ padding: "10px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }}
              />
              {forgotMsg && <div style={{ fontSize: 12, color: "#10B981" }}>{forgotMsg}</div>}
              <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                <button type="button" onClick={() => setShowForgotModal(false)} style={{ flex: 1, padding: "10px", borderRadius: 10, background: "rgba(15,23,42,0.6)", border: "1px solid rgba(255,255,255,0.08)", color: "#CBD5E1", fontSize: 13, cursor: "pointer" }}>Close</button>
                <button type="submit" disabled={forgotLoading} style={{ flex: 1, padding: "10px", borderRadius: 10, background: "linear-gradient(135deg,#6366F1,#4F46E5)", border: "none", color: "#FFF", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>{forgotLoading ? "Sending…" : "Send Email"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
