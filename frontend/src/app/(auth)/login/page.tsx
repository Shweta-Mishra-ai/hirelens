"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const { login, oauthLogin, isLoading, error, clearError } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Listen for Supabase auth state change (like redirect from OAuth)
  useEffect(() => {
    // Check active session on mount
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.access_token && !isLoading && !useAuthStore.getState().token) {
        oauthLogin(session.access_token);
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === "SIGNED_IN" && session?.access_token) {
        try {
          await oauthLogin(session.access_token);
          router.replace("/dashboard");
        } catch (e) {
          console.error("Google Sign-In failed:", e);
        }
      }
    });

    return () => subscription.unsubscribe();
  }, [oauthLogin, router, isLoading]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    clearError();
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch { /* shown via store */ }
  }

  const handleGoogleLogin = async () => {
    clearError();
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: window.location.origin + "/login",
        },
      });
      if (error) throw error;
    } catch (e: any) {
      console.error(e);
      alert(e.message || "Google Sign-in failed");
    }
  };

  const S = {
    page: { minHeight: "100vh", background: "#0D0C0A", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 },
    card: { background: "#17140F", border: "1px solid #2A251C", borderRadius: 18, padding: "32px 28px", width: "100%", maxWidth: 420 },
    inp: { width: "100%", padding: "11px 14px", background: "#131110", border: "1px solid #2A251C", borderRadius: 10, color: "#EDE6D6", fontSize: 14, outline: "none", fontFamily: "inherit", boxSizing: "border-box" as const },
    lbl: { display: "block", fontSize: 11, fontWeight: 700, color: "#9C9483", marginBottom: 6, letterSpacing: 1 },
  };

  return (
    <div style={S.page as React.CSSProperties}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{ width: 38, height: 38, borderRadius: 11, background: "linear-gradient(135deg,#3E5C76,#3E5C76)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>🔎</div>
            <span style={{ fontSize: 22, fontWeight: 900, color: "#EDE6D6", letterSpacing: -1 }}>HireLens</span>
          </div>
          <p style={{ color: "#A79E8C", fontSize: 14, margin: 0 }}>AI Recruiter Intelligence</p>
        </div>
        <div style={S.card}>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: "#EDE6D6", margin: "0 0 24px", letterSpacing: -.5 }}>Sign in</h1>
          {error && (
            <div style={{ padding: "12px 14px", background: "rgba(177,66,38,0.1)", border: "1px solid rgba(177,66,38,0.3)", borderRadius: 10, color: "#D46A4C", fontSize: 13, marginBottom: 20 }}>
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
            <button type="submit" disabled={isLoading} style={{ width: "100%", padding: "12px", borderRadius: 11, background: isLoading ? "#2A251C" : "linear-gradient(135deg,#3E5C76,#2C4258)", border: "none", color: isLoading ? "#6B6355" : "#EDE6D6", fontWeight: 700, fontSize: 14, cursor: isLoading ? "not-allowed" : "pointer", fontFamily: "inherit", marginTop: 4 }}>
              {isLoading ? "Signing in…" : "Sign In"}
            </button>
          </form>

          <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "20px 0" }}>
            <div style={{ flex: 1, height: 1, background: "#2A251C" }} />
            <span style={{ fontSize: 11, color: "#9C9483", fontWeight: 700, letterSpacing: 1 }}>OR</span>
            <div style={{ flex: 1, height: 1, background: "#2A251C" }} />
          </div>

          <button
            onClick={handleGoogleLogin}
            disabled={isLoading}
            style={{
              width: "100%",
              padding: "11px",
              borderRadius: 11,
              background: "none",
              border: "1px solid #2A251C",
              color: "#EDE6D6",
              fontWeight: 600,
              fontSize: 14,
              cursor: isLoading ? "not-allowed" : "pointer",
              fontFamily: "inherit",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 10,
              transition: "all .15s",
            }}
            onMouseOver={e => { (e.currentTarget as HTMLElement).style.borderColor = "#3E5C76"; (e.currentTarget as HTMLElement).style.background = "rgba(62,92,118,0.06)"; }}
            onMouseOut={e => { (e.currentTarget as HTMLElement).style.borderColor = "#2A251C"; (e.currentTarget as HTMLElement).style.background = "none"; }}
          >
            <svg width="18" height="18" viewBox="0 0 18 18">
              <path fill="#EA4335" d="M9 3.6c1.6 0 3 .6 4.1 1.6l3-3C14.3.9 11.9 0 9 0 5.5 0 2.4 2 1 5l3.2 2.5C5 5.2 6.8 3.6 9 3.6z"/>
              <path fill="#4285F4" d="M17.6 9.2c0-.6 0-1.2-.1-1.8H9v3.4h4.8c-.2 1.1-.8 2-1.8 2.6l2.8 2.2c1.7-1.6 2.8-3.9 2.8-6.4z"/>
              <path fill="#FBBC05" d="M4.2 10.5C4 9.9 3.9 9.3 3.9 8.7s.1-1.2.3-1.8L1 4.4C.3 5.7 0 7.2 0 8.7s.3 3 1 4.3l3.2-2.5z"/>
              <path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.8-2.2c-.8.6-1.9.9-3.2.9-2.2 0-4-1.6-4.8-3.8L1 13.2C2.4 16 5.5 18 9 18z"/>
            </svg>
            Continue with Google
          </button>

          <p style={{ textAlign: "center", fontSize: 13, color: "#9C9483", marginTop: 20, marginBottom: 0 }}>
            No account? <Link href="/signup" style={{ color: "#6E90AC", textDecoration: "none", fontWeight: 600 }}>Create one free</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
