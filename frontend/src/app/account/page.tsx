"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ShieldOff, Trash2, Wrench } from "lucide-react";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button, LinkButton } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert, Skeleton } from "@/components/ui/Feedback";
import { useAuthStore } from "@/store/auth";
import { APIError, authAPI, billingAPI, isInAppLink, type PlanUsage } from "@/lib/api";
import { setSignInDestination } from "@/lib/session";

const PLAN_NAMES: Record<PlanUsage["plan"], string> = { free: "Free", pro: "Pro", team: "Team" };


/**
 * What the plan card's button offers, or null when there is nothing to buy.
 * A plan with no end date was set by an operator and doesn't lapse.
 */
function upgradeLabel(plan: string, expiresAt: string | null | undefined): string | null {
  if (plan === "free") return "Upgrade";
  if (!expiresAt) return plan === "team" ? null : "Upgrade to Team";
  return plan === "team" ? "Renew" : "Renew or upgrade";
}

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
                {usage.plan_expires_at && ` · ${PLAN_NAMES[usage.plan]} until ${formatDay(usage.plan_expires_at)}`}
              </div>
            </div>
            {usage.upgrade_url && upgradeLabel(usage.plan, usage.plan_expires_at) && (
              <LinkButton
                variant="primary"
                href={usage.upgrade_url}
                {...(isInAppLink(usage.upgrade_url) ? {} : { target: "_blank", rel: "noopener noreferrer" })}
              >
                {upgradeLabel(usage.plan, usage.plan_expires_at)}
              </LinkButton>
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
      setSignInDestination("/login?deleted=1");
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

/** Shown only to operators (ADMIN_EMAILS); the server checks every operator call. */
function OperatorCard() {
  const token = useAuthStore((s) => s.token);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    authAPI
      .me(token)
      .then((me) => !cancelled && setIsAdmin(Boolean(me.is_admin)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!isAdmin) return null;
  return (
    <Card>
      <CardHeader title="Operator" description="Customers, their usage, and plan changes." />
      <CardBody>
        <LinkButton href="/admin" variant="secondary" icon={<Wrench className="size-4" />}>
          Open operator screen
        </LinkButton>
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
        <OperatorCard />
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
