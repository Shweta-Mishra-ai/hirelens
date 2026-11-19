"use client";
import { useCallback, useEffect, useState } from "react";
import { Search } from "lucide-react";
import { AppShell, PageHeader, RequireAuth } from "@/components/AppShell";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Feedback";
import { useAuthStore } from "@/store/auth";
import {
  APIError,
  adminAPI,
  authAPI,
  type AdminAccountDetail,
  type AdminAccountRow,
  type PlanUsage,
} from "@/lib/api";

const PLANS: PlanUsage["plan"][] = ["free", "pro", "team"];
const PLAN_NAMES: Record<PlanUsage["plan"], string> = { free: "Free", pro: "Pro", team: "Team" };

function day(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/**
 * The selected account: its usage this month, and the plan buttons. A plan
 * change is what an operator records after a customer pays (see
 * docs/DEPLOYMENT.md, "Plans and quotas"); it applies to the next upload.
 */
function AccountDetail({ email, onChanged }: { email: string; onChanged: () => void }) {
  const token = useAuthStore((s) => s.token);
  const [detail, setDetail] = useState<AdminAccountDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<PlanUsage["plan"] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      setDetail(await adminAPI.account(email, token));
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not load this account.");
    }
  }, [email, token]);

  // Mounted per email (key below), so a newly selected account starts empty.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-change: the loader sets loading state, then awaits the API
    void load();
  }, [load]);

  async function changePlan(plan: PlanUsage["plan"]) {
    if (!token || !detail || plan === detail.usage.plan) return;
    if (!window.confirm(`Move ${detail.email} to the ${PLAN_NAMES[plan]} plan?`)) return;
    setSaving(plan);
    setError(null);
    setNotice(null);
    try {
      await adminAPI.setPlan(detail.email, plan, token);
      setNotice(`${detail.email} is now on the ${PLAN_NAMES[plan]} plan. It applies to their next upload.`);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof APIError ? e.message : "The plan could not be changed.");
    } finally {
      setSaving(null);
    }
  }

  return (
    <Card>
      <CardHeader title={email} description={detail ? [detail.full_name, detail.company].filter(Boolean).join(" · ") : undefined} />
      <CardBody className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}
        {!detail ? (
          !error && <Skeleton className="h-24" />
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-content-faint">Plan</dt>
                <dd className="font-medium text-content">{PLAN_NAMES[detail.usage.plan]}</dd>
              </div>
              <div>
                <dt className="text-content-faint">This month</dt>
                <dd className="font-medium text-content">
                  {detail.usage.used}
                  {detail.usage.unlimited ? " analyses (no limit)" : ` of ${detail.usage.limit} analyses`}
                  {detail.usage.in_progress ? ` · ${detail.usage.in_progress} running` : ""}
                </dd>
              </div>
              <div>
                <dt className="text-content-faint">Joined</dt>
                <dd className="text-content">{day(detail.created_at) || "—"}</dd>
              </div>
              <div>
                <dt className="text-content-faint">Account id</dt>
                <dd className="truncate font-mono text-xs text-content-muted">{detail.user_id}</dd>
              </div>
            </dl>
            <div>
              <div className="mb-2 text-sm text-content-faint">Change plan</div>
              <div className="flex flex-wrap gap-2">
                {PLANS.map((plan) => (
                  <Button
                    key={plan}
                    variant={plan === detail.usage.plan ? "primary" : "secondary"}
                    disabled={plan === detail.usage.plan || saving !== null}
                    loading={saving === plan}
                    onClick={() => changePlan(plan)}
                  >
                    {plan === detail.usage.plan ? `${PLAN_NAMES[plan]} (current)` : PLAN_NAMES[plan]}
                  </Button>
                ))}
              </div>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function AdminContent() {
  const token = useAuthStore((s) => s.token);
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [rows, setRows] = useState<AdminAccountRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    authAPI
      .me(token)
      .then((me) => !cancelled && setAllowed(Boolean(me.is_admin)))
      .catch(() => !cancelled && setAllowed(false));
    return () => {
      cancelled = true;
    };
  }, [token]);

  const loadList = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      const res = await adminAPI.accounts(token, submitted || undefined);
      setRows(res.accounts);
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Could not load accounts.");
      setRows([]);
    }
  }, [token, submitted]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-change: the loader sets loading state, then awaits the API
    if (allowed) void loadList();
  }, [allowed, loadList]);

  if (allowed === null) {
    return (
      <AppShell>
        <Skeleton className="h-40" />
      </AppShell>
    );
  }
  if (!allowed) {
    return (
      <AppShell width="narrow">
        <Card>
          <EmptyState
            title="Operators only"
            description="This page is for the people who run this HireLens deployment. Their sign-in emails are listed in ADMIN_EMAILS on the server."
          />
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageHeader
        title="Operator"
        description="Find a customer, see their usage this month, and change their plan after they pay."
      />
      {error && (
        <Alert tone="error" className="mb-5" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <Card>
          <CardHeader title={submitted ? `Accounts matching “${submitted}”` : "Newest accounts"} />
          <CardBody className="space-y-4">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                setSubmitted(query.trim());
              }}
            >
              <div className="flex-1">
                <Input
                  label="Search by email"
                  name="q"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="name@company.com"
                />
              </div>
              <Button type="submit" variant="secondary" className="self-end">
                <Search aria-hidden className="size-4" />
                Search
              </Button>
            </form>
            {rows === null ? (
              <Skeleton className="h-32" />
            ) : rows.length === 0 ? (
              <p className="text-sm text-content-faint">No accounts found.</p>
            ) : (
              <ul className="divide-y divide-line-subtle">
                {rows.map((r) => (
                  <li key={r.user_id}>
                    <button
                      type="button"
                      onClick={() => setSelected(r.email)}
                      aria-pressed={selected === r.email}
                      className="flex w-full items-center justify-between gap-3 py-2.5 text-left text-sm hover:bg-canvas-overlay focus-visible:outline-none focus-visible:shadow-focus"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-content">{r.email}</span>
                        <span className="block truncate text-xs text-content-faint">
                          {[r.full_name, r.company, day(r.created_at)].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs text-content-muted">{PLAN_NAMES[r.plan] ?? r.plan}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
        {selected ? (
          <AccountDetail key={selected} email={selected} onChanged={loadList} />
        ) : (
          <Card>
            <CardBody>
              <p className="text-sm text-content-faint">Select an account to see its usage and change its plan.</p>
            </CardBody>
          </Card>
        )}
      </div>
    </AppShell>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth>
      <AdminContent />
    </RequireAuth>
  );
}
