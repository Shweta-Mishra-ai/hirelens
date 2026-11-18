-- HireLens — plans and usage metering.
--
-- Run after 001-006. Idempotent: safe to re-run.
--
-- Two tables, both written ONLY by the API with the service-role key:
--
--   subscriptions   one row per paying account: which plan it is on.
--   usage_events    an append-only ledger, one row per completed analysis.
--
-- Why not a `plan` column on profiles: profiles carries a "You can edit your
-- own profile" policy, and a user with a Supabase session (every Google
-- sign-in has one) could set their own plan to the top tier from the browser.
--
-- Why not count rows in reports: users can delete reports — through the app
-- or directly — and each deletion would hand quota back. The ledger is never
-- deleted from by any user-reachable path.
--
-- RLS is enabled on both with a read-own policy and NO insert, update or
-- delete policy, so the anon and authenticated roles cannot write either.
-- The service role bypasses RLS.

CREATE TABLE IF NOT EXISTS public.subscriptions (
    user_id             uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    plan                text NOT NULL DEFAULT 'free',
    status              text NOT NULL DEFAULT 'active',
    -- Optional: the payment provider's ids, for reconciliation.
    provider            text,
    provider_customer   text,
    provider_reference  text,
    current_period_end  timestamptz,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT subscriptions_plan_check   CHECK (plan IN ('free', 'pro', 'team')),
    CONSTRAINT subscriptions_status_check CHECK (status IN ('active', 'past_due', 'canceled'))
);

CREATE TABLE IF NOT EXISTS public.usage_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind        text NOT NULL DEFAULT 'analysis',
    report_id   uuid,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- The quota query: this user's events since the start of the month.
CREATE INDEX IF NOT EXISTS idx_usage_events_user_created
    ON public.usage_events (user_id, created_at DESC);

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_events  ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'subscriptions'
      AND policyname = 'You can read your own subscription'
  ) THEN
    CREATE POLICY "You can read your own subscription" ON public.subscriptions
      FOR SELECT USING (user_id = (SELECT auth.uid()));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'usage_events'
      AND policyname = 'You can read your own usage'
  ) THEN
    CREATE POLICY "You can read your own usage" ON public.usage_events
      FOR SELECT USING (user_id = (SELECT auth.uid()));
  END IF;
END $$;
