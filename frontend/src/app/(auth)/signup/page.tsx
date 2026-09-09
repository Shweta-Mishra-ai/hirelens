"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { color, gradient, radius } from "@/lib/design-tokens";
import { Card, Button, TextInput, FieldLabel, AlertBanner, PageShell } from "@/components/ui/primitives";
import { Search, AlertCircle, Mail } from "lucide-react";

export default function SignupPage() {
  const router   = useRouter();
  const { token, sessionChecked, setAuth } = useAuthStore();

  useEffect(() => {
    if (sessionChecked && token) {
      router.replace("/dashboard");
    }
  }, [sessionChecked, token, router]);


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
    <PageShell>
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
        <Card raised style={{ width: "100%", maxWidth: 440, padding: "36px 32px" }}>
          <div className="animate-fade-up">
            {/* Brand */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 24 }}>
              <div style={{
                width: 34, height: 34, borderRadius: radius.sm,
                background: gradient.brand,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}><Search size={17} color="#F5F5F2" strokeWidth={2.5} /></div>
              <span className="font-display" style={{ fontWeight: 600, fontSize: 22, color: color.textPrimary }}>HireLens</span>
            </div>

            {pendingConfirmEmail ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}>
                  <Mail size={44} color={color.brandLight} />
                </div>
                <h2 className="font-display" style={{ fontSize: 22, fontWeight: 600, color: color.textPrimary, marginBottom: 10 }}>Check your inbox</h2>
                <p style={{ fontSize: 14, color: color.textMuted, lineHeight: 1.6, marginBottom: 24 }}>
                  We sent a confirmation link to <strong style={{ color: color.textPrimary }}>{pendingConfirmEmail}</strong>. Please confirm your email to activate your account.
                </p>
                <Link href="/login" style={{
                  display: "inline-block", padding: "11px 24px", borderRadius: radius.md,
                  background: gradient.brandButton, color: "#FFF", fontWeight: 600, fontSize: 13, textDecoration: "none",
                }}>
                  Back to Login
                </Link>
              </div>
            ) : (
              <>
                <h1 className="font-display" style={{ fontSize: 24, fontWeight: 600, color: color.textPrimary, textAlign: "center", margin: "0 0 6px" }}>Create your account</h1>
                <p style={{ fontSize: 13, color: color.textMuted, textAlign: "center", margin: "0 0 24px" }}>Start examining candidate credibility</p>

                {error && (
                  <div style={{ marginBottom: 20 }}>
                    <AlertBanner tone="danger" icon={<AlertCircle size={15} />}>{error}</AlertBanner>
                  </div>
                )}

                <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div>
                    <FieldLabel>Full Name</FieldLabel>
                    <TextInput type="text" required value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Jane Doe" />
                  </div>

                  <div>
                    <FieldLabel>Company / Organization (Optional)</FieldLabel>
                    <TextInput type="text" value={company} onChange={e => setCompany(e.target.value)} placeholder="Acme HR Corp" />
                  </div>

                  <div>
                    <FieldLabel>Work Email</FieldLabel>
                    <TextInput type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="recruiter@company.com" />
                  </div>

                  <div>
                    <FieldLabel>Password (min 8 chars)</FieldLabel>
                    <TextInput type="password" required value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
                  </div>

                  <Button type="submit" disabled={loading} style={{ width: "100%", padding: "12px", marginTop: 6 }}>
                    {loading ? "Creating Account…" : "Create Account"}
                  </Button>
                </form>

                <div style={{ marginTop: 24, textAlign: "center", fontSize: 13, color: color.textMuted }}>
                  Already have an account?{" "}
                  <Link href="/login" style={{ color: color.brandLight, fontWeight: 600, textDecoration: "none" }}>Sign in</Link>
                </div>
              </>
            )}
          </div>
        </Card>
      </div>
    </PageShell>
  );
}
