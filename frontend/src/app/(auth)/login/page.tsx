"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { Search, AlertCircle } from "lucide-react";

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
            boxShadow: "0 0 20px rgba(99,102,241,0.4)"
          }}><Search size={20} color="#FFFFFF" strokeWidth={2.5} /></div>
          <span style={{ fontWeight: 800, fontSize: 24, color: "#F8FAFC", letterSpacing: -0.6 }}>HireLens</span>
        </div>

        <h1 style={{ fontSize: 22, fontWeight: 800, color: "#F8FAFC", textAlign: "center", margin: "0 0 6px" }}>Sign in to HireLens</h1>
        <p style={{ fontSize: 13, color: "#94A3B8", textAlign: "center", margin: "0 0 28px" }}>AI Candidate Credibility Intelligence</p>

        {error && (
          <div style={{ padding: "12px 14px", borderRadius: 10, background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#EF4444", fontSize: 13, marginBottom: 20, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertCircle size={15} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        {/* Google OAuth */}
        <button onClick={handleGoogleLogin} style={{
          width: "100%", padding: "11px 16px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.1)",
          background: "rgba(15, 23, 42, 0.6)", color: "#F8FAFC", fontWeight: 600, fontSize: 13,
          display: "flex", alignItems: "center", justifyContent: "center", gap: 10, cursor: "pointer", marginBottom: 20
        }}>
          <svg width="16" height="16" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335"/>
          </svg>
          Sign in with Google
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
