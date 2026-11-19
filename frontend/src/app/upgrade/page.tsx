"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import QRCode from "qrcode";
import { Check, Copy, Smartphone } from "lucide-react";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Feedback";
import { useAuthStore } from "@/store/auth";
import {
  APIError,
  announceUsageChange,
  billingAPI,
  type PaymentClaim,
  type PlanOffer,
  type PlansInfo,
} from "@/lib/api";
import { cn } from "@/lib/cn";

const PLAN_NAMES: Record<string, string> = { free: "Free", pro: "Pro", team: "Team" };
const STATUS_TEXT: Record<PaymentClaim["status"], string> = {
  pending: "Waiting for verification",
  approved: "Approved",
  rejected: "Not approved",
};

function rupees(amount: number): string {
  return `₹${amount.toLocaleString("en-IN")}`;
}

function day(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/**
 * The upi:// link every UPI app understands (NPCI's deep-link format).
 * Encoded by hand rather than with URLSearchParams, which writes spaces as
 * "+" — some UPI apps show that literally in the payee name.
 */
export function upiLink(upiId: string, payee: string | null, amount: number, note: string): string {
  const params: [string, string][] = [
    ["pa", upiId],
    ["pn", payee || upiId],
    ["am", amount.toFixed(2)],
    ["cu", "INR"],
    ["tn", note],
  ];
  return `upi://pay?${params.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&")}`;
}

function PayPanel({ info, offer, waiting, onSubmitted }: {
  info: PlansInfo;
  offer: PlanOffer;
  waiting: boolean;
  onSubmitted: () => void;
}) {
  const token = useAuthStore((s) => s.token);
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const link = useMemo(
    () => upiLink(info.upi_id ?? "", info.payee_name, offer.price_inr, `HireLens ${PLAN_NAMES[offer.plan]}`),
    [info.upi_id, info.payee_name, offer],
  );

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(link, { margin: 1, width: 220 })
      .then((url) => !cancelled && setQr(url))
      .catch(() => !cancelled && setQr(null));
    return () => {
      cancelled = true;
    };
  }, [link]);

  async function copyId() {
    try {
      await navigator.clipboard.writeText(info.upi_id ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked: the ID is on screen to copy by hand.
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !reference.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await billingAPI.submitPayment(offer.plan, reference.trim(), token);
      setDone(true);
      setReference("");
      onSubmitted();
    } catch (err) {
      setError(err instanceof APIError ? err.message : "Your payment details could not be sent. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Pay ${rupees(offer.price_inr)} for ${PLAN_NAMES[offer.plan]}`}
        description={`${info.period_days} days of ${PLAN_NAMES[offer.plan]}. Pay with any UPI app — Google Pay, PhonePe, Paytm, BHIM or your bank's app.`}
      />
      <CardBody className="space-y-5">
        <div className="flex flex-wrap items-start gap-6">
          <div className="flex size-[220px] items-center justify-center rounded-lg bg-white p-2">
            {qr ? (
              // eslint-disable-next-line @next/next/no-img-element -- a generated data: URL, nothing to optimise
              <img src={qr} alt={`UPI QR code: pay ${rupees(offer.price_inr)} to ${info.upi_id}`} width={204} height={204} />
            ) : (
              <Skeleton className="size-[204px]" />
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-3 text-sm">
            <div>
              <div className="text-content-faint">UPI ID</div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-base text-content">{info.upi_id}</span>
                <button
                  type="button"
                  onClick={copyId}
                  className="rounded p-1 text-content-faint hover:text-content focus-visible:outline-none focus-visible:shadow-focus"
                  aria-label="Copy UPI ID"
                >
                  {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
                </button>
              </div>
            </div>
            {info.payee_name && (
              <div>
                <div className="text-content-faint">Name shown in your UPI app</div>
                <div className="text-content">{info.payee_name}</div>
              </div>
            )}
            <div>
              <div className="text-content-faint">Amount</div>
              <div className="text-content">{rupees(offer.price_inr)}</div>
            </div>
            <a href={link} className="inline-block sm:hidden">
              <Button variant="secondary">
                <Smartphone aria-hidden className="size-4" />
                Open UPI app
              </Button>
            </a>
          </div>
        </div>

        <ol className="list-decimal space-y-1 pl-5 text-sm text-content-muted">
          <li>Scan the code with any UPI app, or pay to the UPI ID above. Pay exactly {rupees(offer.price_inr)}.</li>
          <li>Copy the transaction reference (UTR, usually 12 digits) from the payment&apos;s details in your app.</li>
          <li>Enter it below. We check it against our bank statement and switch your plan.</li>
        </ol>

        {done && (
          <Alert tone="success" title="Thanks — we've got your payment details">
            We&apos;ll verify the payment and switch your plan. You can see its status below.
          </Alert>
        )}
        {error && <Alert tone="error">{error}</Alert>}
        {waiting && !done ? (
          <Alert tone="info">
            You already have a payment waiting to be verified. You can send another once it has been checked.
          </Alert>
        ) : (
          <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
            <div className="min-w-[14rem] flex-1">
              <Input
                label="Transaction reference (UTR)"
                name="reference"
                inputMode="numeric"
                autoComplete="off"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="e.g. 402156789012"
              />
            </div>
            <Button type="submit" variant="primary" loading={busy} disabled={!reference.trim()}>
              I&apos;ve paid
            </Button>
          </form>
        )}
      </CardBody>
    </Card>
  );
}

function UpgradeContent() {
  const token = useAuthStore((s) => s.token);
  const [info, setInfo] = useState<PlansInfo | null>(null);
  const [claims, setClaims] = useState<PaymentClaim[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<PlanOffer["plan"] | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [plans, mine] = await Promise.all([billingAPI.plans(token), billingAPI.myPayments(token)]);
      setInfo(plans);
      setClaims(mine.payments);
      setSelected((current) => current ?? plans.plans[0]?.plan ?? null);
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not load the plans.");
    }
  }, [token]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-change: the loader sets loading state, then awaits the API
    void load();
  }, [load]);

  const waiting = claims.some((c) => c.status === "pending");
  const offer = info?.plans.find((p) => p.plan === selected) ?? null;

  if (error) {
    return (
      <AppShell width="narrow">
        <Alert tone="error">{error}</Alert>
      </AppShell>
    );
  }
  if (!info) {
    return (
      <AppShell width="narrow">
        <Skeleton className="h-64" />
      </AppShell>
    );
  }

  const usage = info.usage;
  return (
    <AppShell width="narrow">
      <PageHeader
        title="Upgrade"
        description={
          <>
            You&apos;re on the {PLAN_NAMES[usage.plan]} plan
            {usage.plan_expires_at ? ` until ${day(usage.plan_expires_at)}` : ""}
            {usage.unlimited ? "." : `: ${usage.used} of ${usage.limit} analyses used this month.`}
          </>
        }
      />
      {info.plans.length === 0 || !info.upi_id ? (
        <Card>
          <EmptyState
            title="Upgrades aren't available in the app yet"
            description="Contact us and we'll set up your plan."
            action={
              <Link href="/contact">
                <Button variant="primary">Contact us</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Plan">
            {info.plans.map((p) => (
              <button
                key={p.plan}
                type="button"
                role="radio"
                aria-checked={selected === p.plan}
                onClick={() => setSelected(p.plan)}
                className={cn(
                  "rounded-lg border p-4 text-left transition-colors focus-visible:outline-none focus-visible:shadow-focus",
                  selected === p.plan ? "border-brand-500 bg-brand-500/10" : "border-line hover:bg-canvas-overlay",
                )}
              >
                <div className="text-base font-semibold text-content">{PLAN_NAMES[p.plan]}</div>
                <div className="mt-1 text-lg text-content">
                  {rupees(p.price_inr)}
                  <span className="text-sm text-content-faint"> / {info.period_days} days</span>
                </div>
                <div className="mt-1 text-sm text-content-muted">
                  {p.monthly_analyses ? `${p.monthly_analyses} analyses a month` : "No monthly limit on analyses"}
                </div>
              </button>
            ))}
          </div>
          {offer && (
            <PayPanel
              info={info}
              offer={offer}
              waiting={waiting}
              onSubmitted={() => {
                announceUsageChange();
                void load();
              }}
            />
          )}
        </div>
      )}

      {claims.length > 0 && (
        <Card className="mt-5">
          <CardHeader title="Your payments" />
          <CardBody>
            <ul className="divide-y divide-line-subtle text-sm">
              {claims.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <span className="min-w-0">
                    <span className="block text-content">
                      {PLAN_NAMES[c.plan]} · {rupees(c.amount_inr)} · <span className="font-mono">{c.reference}</span>
                    </span>
                    <span className="block text-xs text-content-faint">
                      {day(c.created_at)}
                      {c.note ? ` · ${c.note}` : ""}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "shrink-0 text-xs font-medium",
                      c.status === "approved" ? "text-positive" : c.status === "rejected" ? "text-critical" : "text-caution",
                    )}
                  >
                    {STATUS_TEXT[c.status]}
                  </span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </AppShell>
  );
}

export default function UpgradePage() {
  return (
    <RequireAuth>
      <UpgradeContent />
    </RequireAuth>
  );
}
