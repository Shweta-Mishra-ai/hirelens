"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Feedback";
import { Card } from "@/components/ui/Card";
import { AuthLayout, AuthFooterLink, GoogleButton, OrDivider } from "../AuthLayout";

/** Google sign-in only works when Supabase is wired up; hide it otherwise. */
function googleConfigured() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  return Boolean(url) && !url!.includes("placeholder") && !url!.includes("your-project");
}

export default function LoginPage() {
  const router = useRouter();
  const { token, hasHydrated, setAuth } = useAuthStore();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);
  const [forgotMsg, setForgotMsg] = useState<string | null>(null);

  useEffect(() => {
    if (hasHydrated && token) router.replace("/dashboard");
  }, [hasHydrated, token, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authAPI.login(email.trim(), password);
      setAuth(res.access_token, res.user);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof APIError ? err.message : "Could not sign in. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogle() {
    setError(null);
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/dashboard` },
    });
    if (oauthError) setError(oauthError.message);
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault();
    if (!forgotEmail.trim()) return;
    setForgotLoading(true);
    setForgotMsg(null);
    try {
      const res = await authAPI.forgotPassword(forgotEmail.trim());
      setForgotMsg(res.message);
    } catch (err) {
      setForgotMsg(
        err instanceof APIError ? err.message : "Could not send the reset email. Try again later.",
      );
    } finally {
      setForgotLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Pick up where you left off with your candidate files."
      footer={<AuthFooterLink prompt="New to HireLens?" href="/signup" label="Create an account" />}
    >
      {error && (
        <Alert tone="error" className="mb-5" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {googleConfigured() && (
        <>
          <GoogleButton onClick={handleGoogle} label="Continue with Google" />
          <OrDivider />
        </>
      )}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <Input
          label="Work email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
        />
        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••••"
          hint={
            <button
              type="button"
              onClick={() => {
                setForgotEmail(email);
                setForgotOpen(true);
              }}
              className="text-xs text-brand-400 underline-offset-4 hover:underline"
            >
              Forgot password?
            </button>
          }
        />
        <Button type="submit" variant="primary" size="lg" fullWidth loading={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      {forgotOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="forgot-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-5 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setForgotOpen(false);
          }}
        >
          <Card className="w-full max-w-sm animate-fade-in p-6">
            <h2 id="forgot-title" className="text-lg font-semibold text-content">
              Reset your password
            </h2>
            <p className="mt-1 text-sm text-content-muted">
              We&apos;ll email reset instructions to your registered address.
            </p>
            <form onSubmit={handleForgot} className="mt-5 space-y-4">
              <Input
                label="Email"
                type="email"
                required
                autoFocus
                value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
                placeholder="you@company.com"
              />
              {forgotMsg && <Alert tone="info">{forgotMsg}</Alert>}
              <div className="flex gap-2.5">
                <Button type="button" fullWidth onClick={() => setForgotOpen(false)}>
                  Close
                </Button>
                <Button type="submit" variant="primary" fullWidth loading={forgotLoading}>
                  Send email
                </Button>
              </div>
            </form>
          </Card>
        </div>
      )}
    </AuthLayout>
  );
}
