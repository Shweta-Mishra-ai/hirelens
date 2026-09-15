"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { MailCheck } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { authAPI, APIError } from "@/lib/api";
import { useGoogleAuth } from "@/hooks/useGoogleAuth";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Feedback";
import { AuthLayout, AuthFooterLink, GoogleButton, OrDivider } from "../AuthLayout";

const MIN_PASSWORD_LENGTH = 8;

/** Sign-up failures that aren't about a single field. */
function signupError(err: unknown): string {
  if (!(err instanceof APIError)) return "Could not create your account. Please try again.";
  if (err.status === 0 || err.code === "network_error") {
    return "Can't reach the HireLens server. Check your connection and try again.";
  }
  if (err.code === "timeout") {
    return "The server took too long to respond. It may be waking up — try again in a few seconds.";
  }
  if (err.status === 429) {
    return err.code === "capacity_limit_exceeded"
      ? "HireLens has reached its registration limit. Contact your administrator for access."
      : "Too many sign-up attempts from this network. Wait a few minutes and try again.";
  }
  if (err.status >= 500) {
    return "The server had a problem creating your account. This is on our side — please try again shortly.";
  }
  return err.message;
}

export default function SignupPage() {
  const router = useRouter();
  const { token, hasHydrated, setAuth } = useAuthStore();
  const google = useGoogleAuth();

  const [fullName, setFullName] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Per-field errors are kept separate from the form-level error so a
  // password-length problem points at the password, not at a banner.
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [pendingConfirmEmail, setPendingConfirmEmail] = useState<string | null>(null);

  useEffect(() => {
    if (hasHydrated && token) router.replace("/dashboard");
  }, [hasHydrated, token, router]);

  function validate() {
    const errs: Record<string, string> = {};
    if (!fullName.trim()) errs.fullName = "Enter your name.";
    else if (fullName.trim().length < 2) errs.fullName = "That name looks too short.";
    if (!email.trim()) errs.email = "Enter your work email.";
    if (!password) errs.password = "Choose a password.";
    else if (password.length < MIN_PASSWORD_LENGTH) {
      errs.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!validate()) return;

    setLoading(true);
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
      if (err instanceof APIError && err.status === 409) {
        // A duplicate email is a fact about one field, so it belongs on
        // that field rather than in a generic banner.
        setFieldErrors({ email: "An account with this email already exists. Sign in instead." });
      } else if (err instanceof APIError && err.status === 422) {
        // The API client turns FastAPI's validation payload into
        // "Email: ..." / "Password: ..." — route it to the right field.
        const routed: Record<string, string> = {};
        for (const part of err.message.split(/(?=\b(?:Email|Password|Full name|Company):)/)) {
          const m = part.match(/^(Email|Password|Full name|Company):\s*(.+)$/);
          if (!m) continue;
          const key = { Email: "email", Password: "password", "Full name": "fullName", Company: "company" }[m[1]];
          if (key) routed[key] = m[2].trim();
        }
        if (Object.keys(routed).length) setFieldErrors(routed);
        else setError(err.message);
      } else {
        setError(signupError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  if (pendingConfirmEmail) {
    return (
      <AuthLayout
        title="Check your inbox"
        subtitle="One more step before you can sign in."
        footer={<AuthFooterLink prompt="Already confirmed?" href="/login" label="Sign in" />}
      >
        <div className="rounded-lg border border-line bg-canvas-raised p-6 text-center">
          <MailCheck aria-hidden className="mx-auto size-8 text-brand-400" />
          <p className="mt-4 text-sm leading-relaxed text-content-muted">
            We sent a confirmation link to{" "}
            <span className="font-medium text-content">{pendingConfirmEmail}</span>. Open it to
            activate your account.
          </p>
          <Link href="/login" className="mt-5 inline-block">
            <Button variant="primary">Back to sign in</Button>
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start reviewing candidate files with the evidence attached."
      footer={<AuthFooterLink prompt="Already have an account?" href="/login" label="Sign in" />}
    >
      {error && (
        <Alert tone="error" className="mb-5" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {google.error && (
        <Alert tone="error" className="mb-5" onDismiss={google.clearError}>
          {google.error}
        </Alert>
      )}

      <GoogleButton
        onClick={google.signIn}
        label="Sign up with Google"
        loading={google.redirecting}
        disabled={google.state.status !== "ready"}
        reason={google.state.status === "unconfigured" ? google.state.reason : undefined}
      />
      <OrDivider />

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <Input
          label="Full name"
          name="name"
          autoComplete="name"
          required
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          error={fieldErrors.fullName}
          placeholder="Jane Okafor"
        />
        <Input
          label="Company"
          name="organization"
          autoComplete="organization"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder="Acme Talent"
          hint={<span className="text-xs text-content-faint">Optional</span>}
        />
        <Input
          label="Work email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
          placeholder="you@company.com"
        />
        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          placeholder="••••••••••"
          hint={
            <span className="text-xs text-content-faint">
              {MIN_PASSWORD_LENGTH}+ characters
            </span>
          }
        />
        <Button type="submit" variant="primary" size="lg" fullWidth loading={loading}>
          {loading ? "Creating account…" : "Create account"}
        </Button>
      </form>

      <p className="mt-5 text-xs leading-relaxed text-content-faint">
        You are responsible for how you use HireLens output. Scores and flags are
        prompts to investigate, not hiring decisions.
      </p>
    </AuthLayout>
  );
}
