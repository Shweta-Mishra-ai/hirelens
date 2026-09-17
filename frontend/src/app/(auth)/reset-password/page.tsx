"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authAPI, APIError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Feedback";
import { AuthLayout, AuthFooterLink } from "../AuthLayout";
import { captureResetLink, recaptureResetLink, passwordStrength } from "@/lib/resetLink";

/**
 * Where a password reset link lands.
 *
 * The token arrives in the URL fragment when Supabase sent the email, so it is
 * read on the client from window.location rather than through
 * useSearchParams() — a fragment never reaches the server or a router.
 *
 * It is also cleared from the address bar as soon as it has been read. A
 * recovery token is a bearer credential: leaving it in the URL puts it in
 * browser history and in whatever the person pastes when they ask for help.
 */

function resetError(err: unknown): { message: string; hint?: string } {
  if (!(err instanceof APIError)) {
    return { message: "Something went wrong. Please try again." };
  }
  if (err.status === 0 || err.code === "network_error") {
    return {
      message: "Can't reach the HireLens server.",
      hint: "Check your connection and try again.",
    };
  }
  if (err.status === 429) {
    return {
      message: "Too many attempts.",
      hint: "Wait a minute, then try again.",
    };
  }
  if (err.status === 401) {
    return {
      message: err.message,
      hint: "Reset links work once and expire. Ask for a fresh one from the sign-in page.",
    };
  }
  if (err.status === 422 || err.status === 400) {
    // The API and the identity provider both have a say in what counts as an
    // acceptable password, and their message names the specific rule.
    return { message: err.message };
  }
  if (err.status >= 500) {
    return {
      message: "The server had a problem updating your password.",
      hint: "This is on our side. Please try again in a moment.",
    };
  }
  return { message: err.message };
}

const STRENGTH_STYLES = [
  "bg-critical",
  "bg-critical",
  "bg-caution",
  "bg-brand-500",
  "bg-positive",
] as const;

export default function ResetPasswordPage() {
  const router = useRouter();

  const [token, setToken] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    // captureResetLink() answers from the first read of this page load, so it
    // is unaffected by the scrub below or by this effect running more than
    // once.
    const apply = (link: { token: string | null; error: string | null }) => {
      setToken(link.token);
      setLinkError(link.error);
      setReady(true);
      if (link.token) {
        // Drop the credential from the address bar without adding a history
        // entry — a back press should not resurrect it.
        window.history.replaceState(null, "", window.location.pathname);
      }
    };

    apply(captureResetLink());

    // A second link, opened in a tab already showing this page, only changes
    // the fragment. Nothing remounts, so without this the page keeps showing
    // whatever the first link said — usually "that link won't work", while the
    // good token sits unread in the URL.
    const onHashChange = () => {
      const next = recaptureResetLink();
      if (!next.token && !next.error) return;
      setDone(false);
      setError(null);
      apply(next);
    };

    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const strength = passwordStrength(password);
  const mismatch = confirm.length > 0 && password !== confirm;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || loading) return;
    if (password !== confirm) {
      setError({ message: "Those two passwords don't match." });
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await authAPI.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(resetError(err));
    } finally {
      setLoading(false);
    }
  }

  // ── The link itself was refused, or carried no token ─────────────────────
  if (ready && !token) {
    return (
      <AuthLayout
        title="That link won't work"
        subtitle="Reset links are single-use and expire. Ask for a new one and it will."
        footer={<AuthFooterLink prompt="Remembered it?" href="/login" label="Back to sign in" />}
      >
        <Alert tone="error" title="This password reset link is not valid" className="mb-6">
          {linkError ??
            "It may have expired, already been used, or been cut short when it was copied."}
        </Alert>
        <Button variant="primary" fullWidth onClick={() => router.push("/login")}>
          Request a new link
        </Button>
      </AuthLayout>
    );
  }

  // ── Done ─────────────────────────────────────────────────────────────────
  if (done) {
    return (
      <AuthLayout
        title="Password updated"
        subtitle="Your new password is active. Everything else is exactly where you left it."
        footer={<AuthFooterLink prompt="Need an account?" href="/signup" label="Create one" />}
      >
        <Alert tone="success" title="You can sign in with your new password" className="mb-6">
          For your security, any other device still signed in with the old password
          will need it again.
        </Alert>
        <Button variant="primary" fullWidth onClick={() => router.push("/login")}>
          Go to sign in
        </Button>
      </AuthLayout>
    );
  }

  // ── The form ─────────────────────────────────────────────────────────────
  return (
    <AuthLayout
      title="Choose a new password"
      subtitle="Pick something you don't use anywhere else."
      footer={<AuthFooterLink prompt="Remembered it?" href="/login" label="Back to sign in" />}
    >
      {error && (
        <Alert
          tone="error"
          title={error.message}
          className="mb-5"
          onDismiss={() => setError(null)}
        >
          {error.hint}
        </Alert>
      )}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div>
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            autoFocus
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            hint="At least 8 characters"
          />
          {password && (
            <div className="mt-2 flex items-center gap-2">
              <div
                className="h-1 flex-1 overflow-hidden rounded-full bg-canvas-inset"
                role="presentation"
              >
                <div
                  className={`h-full rounded-full transition-all ${STRENGTH_STYLES[strength.score]}`}
                  style={{ width: `${Math.max(strength.score, 1) * 25}%` }}
                />
              </div>
              <span className="text-xs text-content-faint">{strength.label}</span>
            </div>
          )}
        </div>

        <Input
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={mismatch ? "These don't match yet." : null}
        />

        <Button
          type="submit"
          variant="primary"
          fullWidth
          loading={loading}
          disabled={!ready || !token || password.length < 8 || password !== confirm}
        >
          Update password
        </Button>
      </form>
    </AuthLayout>
  );
}
