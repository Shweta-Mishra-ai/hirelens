"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ShieldOff, Trash2 } from "lucide-react";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert, Skeleton } from "@/components/ui/Feedback";
import { useAuthStore } from "@/store/auth";
import { APIError, authAPI, billingAPI, type PlanUsage } from "@/lib/api";

const PLAN_NAMES: Record<PlanUsage["plan"], string> = { free: "Free", pro: "Pro", team: "Team" };

function formatDay(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function PlanCard() {
  const token = useAuthStore((s) => s.token);
  const [usage, setUsage] = useState<PlanUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    billingAPI
      .usage(token)
      .then((u) => !cancelled && setUsage(u))
      .catch((e) => !cancelled && setError(e instanceof APIError ? e.message : "Could not load your plan."));
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <Card>
      <CardHeader title="Plan and usage" description="Analyses are counted per calendar month (UTC)." />
      <CardBody>
        {error ? (
          <Alert tone="error">{error}</Alert>
        ) : !usage ? (
          <Skeleton className="h-12" />
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="text-lg font-semibold text-content">{PLAN_NAMES[usage.plan] ?? usage.plan} plan</div>
              <div className="mt-0.5 text-sm text-content-muted">
                {usage.unlimited
                  ? `${usage.used} analyses this month — no monthly limit`
                  : `${usage.used} of ${usage.limit} analyses used this month`}
                {usage.period_end && ` · resets ${formatDay(usage.period_end)}`}
              </div>
            </div>
            {usage.upgrade_url && usage.plan === "free" && (
              <a href={usage.upgrade_url} target="_blank" rel="noopener noreferrer">
                <Button variant="primary">Upgrade</Button>
              </a>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function SessionsCard() {
  const { token, logout } = useAuthStore();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signOutEverywhere() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await authAPI.logoutAll(token);
      logout();
      router.replace("/login");
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not sign out your other devices.");
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Sessions"
        description="Signed in on a shared or lost device? End every session, this one included."
      />
      <CardBody className="space-y-3">
        {error && <Alert tone="error">{error}</Alert>}
        <Button variant="secondary" onClick={signOutEverywhere} loading={busy}>
          <ShieldOff aria-hidden className="size-4" />
          Sign out of all devices
        </Button>
      </CardBody>
    </Card>
  );
}

/**
 * Self-serve deletion. The email has to be typed, not clicked through: this
 * is the one action in the app that cannot be undone.
 */
function DeleteAccountCard() {
  const { user, token, logout } = useAuthStore();
  const router = useRouter();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const email = user?.email ?? "";
  const matches = email !== "" && typed.trim().toLowerCase() === email.toLowerCase();

  const remove = useCallback(async () => {
    if (!token || !matches) return;
    setBusy(true);
    setError(null);
    try {
      await authAPI.deleteAccount(typed.trim(), token);
      logout();
      router.replace("/login?deleted=1");
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Your account could not be deleted. Please try again.");
      setBusy(false);
    }
  }, [token, matches, typed, logout, router]);

  return (
    <Card className="border-critical/40">
      <CardHeader
        title="Delete account"
        description="Permanently delete your account and everything in it. This cannot be undone."
      />
      <CardBody className="space-y-4">
        <ul className="list-disc space-y-1 pl-5 text-sm text-content-muted">
          <li>Every candidate report, with its notes, comments and votes</li>
          <li>Teams you own — for every member — and your place in other teams</li>
          <li>Saved job descriptions, your plan and usage history</li>
        </ul>
        <p className="text-sm text-content-muted">
          Download anything you want to keep first — the dashboard can{" "}
          <Link href="/dashboard" className="text-content underline underline-offset-2">
            export your reports as CSV
          </Link>
          .
        </p>
        {error && <Alert tone="error">{error}</Alert>}
        <Input
          label={`Type ${email || "your email"} to confirm`}
          name="confirm-email"
          autoComplete="off"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={email}
        />
        <Button variant="danger" onClick={remove} disabled={!matches} loading={busy}>
          <Trash2 aria-hidden className="size-4" />
          Delete my account
        </Button>
      </CardBody>
    </Card>
  );
}

function AccountContent() {
  const user = useAuthStore((s) => s.user);
  return (
    <AppShell width="narrow">
      <PageHeader title="Account" description={user?.email} />
      <div className="space-y-5">
        <PlanCard />
        <SessionsCard />
        <DeleteAccountCard />
      </div>
    </AppShell>
  );
}

export default function AccountPage() {
  return (
    <RequireAuth>
      <AccountContent />
    </RequireAuth>
  );
}
