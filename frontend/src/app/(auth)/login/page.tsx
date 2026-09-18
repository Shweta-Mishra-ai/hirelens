"use client";
import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { useGoogleAuth } from "@/hooks/useGoogleAuth";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Feedback";
import { Card } from "@/components/ui/Card";
import { AuthLayout, AuthFooterLink, GoogleButton, OrDivider } from "../AuthLayout";
import { InviteBanner } from "@/components/InviteBanner";
import { readInviteParams } from "@/lib/invite";

/**
 * Turn a sign-in failure into something the person can act on.
 *
 * The previous handler showed `err.message` for everything, so a rate limit,
 * an unconfirmed email and a wrong password were indistinguishable — and a
 * network failure read as though the credentials were wrong.
 */
function signInError(err: unknown): { message: string; hint?: string } {
  if (!(err instanceof APIError)) {
    return { message: "Something went wrong signing you in. Please try again." };
  }

  if (err.status === 0 || err.code === "network_error") {
    return {
      message: "Can't reach the HireLens server.",
      hint: "Check your connection. If you're on a VPN or office network, it may be blocking the API.",
    };
  }
  if (err.code === "timeout") {
    return {
      message: "The server took too long to respond.",
      hint: "It may be waking up from idle. Try again in a few seconds.",
    };
  }
  if (err.status === 429) {
    return {
      message: "Too many sign-in attempts from this network.",
      hint: "For security, sign-in is limited to 10 attempts every 15 minutes. Wait a few minutes and try again.",
    };
  }
  if (err.status === 401) {
    // The API deliberately does not reveal whether the account exists, and
    // neither should this copy.
    return {
      message: err.message.toLowerCase().includes("confirm")
        ? err.message
        : "That email and password don't match.",
      hint: err.message.toLowerCase().includes("confirm")
        ? "Open the confirmation link we emailed you, then sign in."
        : "Check for typos, or reset your password if you've forgotten it.",
    };
  }
  if (err.status >= 500) {
    return {
      message: "The server had a problem signing you in.",
      hint: "This is on our side, not yours. Please try again in a moment.",
    };
  }
  return { message: err.message };
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Signing in is what accepts a pending invite, so the link has to work
  // here too — not only on signup, where it happens to point.
  const invite = readInviteParams(searchParams);
  const { token, hasHydrated, setAuth } = useAuthStore();
  const google = useGoogleAuth();

  // Landing here because a session ended is different from choosing to sign
  // in, and saying so is the difference between "the app logged me out for no
  // reason" and "my session ran out".
  const sessionEnded = searchParams.get("session") === "expired";

  const [email, setEmail] = useState(invite.email ?? "");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null);

  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);
  const [forgotMsg, setForgotMsg] = useState<{ tone: "success" | "error"; text: string } | null>(
    null,
  );

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
      setError(signInError(err));
    } finally {
      setLoading(false);
    }
  }

  function openForgot() {
    // Carry over whatever they already typed — asking for it twice on the
    // screen where they have just mistyped it is its own small cruelty.
    setForgotEmail(email.trim());
    setForgotMsg(null);
    setForgotOpen(true);
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault();
    if (!forgotEmail.trim()) return;
    setForgotLoading(true);
    setForgotMsg(null);
    try {
      const res = await authAPI.forgotPassword(forgotEmail.trim());
      setForgotMsg({ tone: "success", text: res.message });
    } catch (err) {
      // A failure here is never "no such account" — the API answers the same
      // either way on purpose — so it is always something to try again.
      setForgotMsg({
        tone: "error",
        text:
          err instanceof APIError
            ? err.message
            : "Could not send the reset email. Check your connection and try again.",
      });
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
      {invite.email && <InviteBanner email={invite.email} mode="login" />}
      {sessionEnded && !error && (
        <Alert tone="info" title="Your session has ended" className="mb-5">
          Sign in again to pick up where you left off — nothing has been lost.
        </Alert>
      )}
      {error && (
        <Alert tone="error" title={error.message} className="mb-5" onDismiss={() => setError(null)}>
          {error.hint}
        </Alert>
      )}

      {google.error && (
        <Alert tone="error" className="mb-5" onDismiss={google.clearError}>
          {google.error}
        </Alert>
      )}

      <GoogleButton
        onClick={google.signIn}
        label="Continue with Google"
        loading={google.redirecting}
        disabled={google.state.status !== "ready"}
        reason={google.state.status === "unconfigured" ? google.state.reason : undefined}
      />
      <OrDivider />

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
              onClick={openForgot}
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
              {forgotMsg && <Alert tone={forgotMsg.tone}>{forgotMsg.text}</Alert>}
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


/**
 * useSearchParams() reads the invite parameters, and Next refuses to
 * prerender a page that calls it unless the call sits under a Suspense
 * boundary. The fallback is never really seen — the params are in the URL
 * the browser already has — but without this the build fails.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
