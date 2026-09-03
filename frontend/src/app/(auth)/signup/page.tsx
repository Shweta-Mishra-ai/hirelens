"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";

export default function SignupPage() {
  const router   = useRouter();
  const { token, hasHydrated, setAuth } = useAuthStore();

  useEffect(() => {
    if (hasHydrated && token) {
      router.replace("/dashboard");
    }
  }, [hasHydrated, token, router]);


  const [fullName, setFullName] = useState("");
  const [company, setCompany]   = useState("");
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");

  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [pendingConfirmEmail, setPendingConfirmEmail] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName.trim() || !email.trim() || !password) return;
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await authAPI.signup({
        full_name: fullName.trim(),
        company: company.trim() || undefined,
        email: email.trim(),
        password,
      });

      if (res.requires_email_confirmation || !res.access_token) {
        setPendingConfirmEmail(email.trim());
      } else {
        setAuth(res.access_token, res.user);
        router.replace("/dashboard");
      }
    } catch (err) {
      setError(err instanceof APIError ? err.message : "Registration failed. Try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0B0F17", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div className="animate-fade-up" style={{
        width: "100%", maxWidth: 460,
        background: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(16px)",
        border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 24, padding: "40px 36px",
        boxShadow: "0 12px 40px -10px rgba(0,0,0,0.6)"
      }}>
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 24 }}>
          <div style={{
            width: 38, height: 38, borderRadius: 12,
            background: "linear-gradient(135deg, #6366F1, #8B5CF6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 20, boxShadow: "0 0 20px rgba(99,102,241,0.4)"
          }}>🔎</div>
          <span style={{ fontWeight: 800, fontSize: 24, color: "#F8FAFC", letterSpacing: -0.6 }}>HireLens</span>
        </div>

        {pendingConfirmEmail ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 44, marginBottom: 16 }}>📧</div>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F8FAFC", marginBottom: 10 }}>Check Your Inbox</h2>
            <p style={{ fontSize: 14, color: "#94A3B8", lineHeight: 1.6, marginBottom: 24 }}>
              We sent a confirmation link to <strong style={{ color: "#F8FAFC" }}>{pendingConfirmEmail}</strong>. Please confirm your email to activate your account.
            </p>
            <Link href="/login" style={{ display: "inline-block", padding: "10px 24px", borderRadius: 10, background: "linear-gradient(135deg,#6366F1,#4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 13, textDecoration: "none" }}>
              Back to Login
            </Link>
          </div>
        ) : (
          <>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: "#F8FAFC", textAlign: "center", margin: "0 0 6px" }}>Create Recruiter Account</h1>
            <p style={{ fontSize: 13, color: "#94A3B8", textAlign: "center", margin: "0 0 24px" }}>Start examining candidate credibility</p>

            {error && (
              <div style={{ padding: "12px 14px", borderRadius: 10, background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#EF4444", fontSize: 13, marginBottom: 20 }}>
                ⚠️ {error}
              </div>
            )}

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#CBD5E1", marginBottom: 4 }}>Full Name</label>
                <input type="text" required value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Jane Doe" style={{ width: "100%", boxSizing: "border-box", padding: "10px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }} />
              </div>

              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#CBD5E1", marginBottom: 4 }}>Company / Organization (Optional)</label>
                <input type="text" value={company} onChange={e => setCompany(e.target.value)} placeholder="Acme HR Corp" style={{ width: "100%", boxSizing: "border-box", padding: "10px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }} />
              </div>

              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#CBD5E1", marginBottom: 4 }}>Work Email</label>
                <input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="recruiter@company.com" style={{ width: "100%", boxSizing: "border-box", padding: "10px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }} />
              </div>

              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#CBD5E1", marginBottom: 4 }}>Password (min 8 chars)</label>
                <input type="password" required value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" style={{ width: "100%", boxSizing: "border-box", padding: "10px 14px", background: "rgba(15,23,42,0.7)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, color: "#F8FAFC", fontSize: 13, outline: "none" }} />
              </div>

              <button type="submit" disabled={loading} style={{ width: "100%", padding: "12px", borderRadius: 12, border: "none", background: "linear-gradient(135deg, #6366F1, #4F46E5)", color: "#FFF", fontWeight: 700, fontSize: 14, cursor: "pointer", marginTop: 6 }}>
                {loading ? "Creating Account…" : "Create Account"}
              </button>
            </form>

            <div style={{ marginTop: 24, textAlign: "center", fontSize: 13, color: "#94A3B8" }}>
              Already have an account?{" "}
              <Link href="/login" style={{ color: "#818CF8", fontWeight: 600, textDecoration: "none" }}>Sign in</Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
