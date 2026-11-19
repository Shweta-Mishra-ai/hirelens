-- HireLens — UPI payments, verified by an operator.
--
-- Run after 001-009. Idempotent: safe to re-run.
--
-- No payment gateway: the customer pays the operator's UPI ID from any UPI
-- app and submits the transaction reference (UTR) here. An operator checks it
-- against the bank statement and approves or rejects it on the operator
-- screen; approval grants the plan for a period (subscriptions.
-- current_period_end, sql/007).
--
-- Written only by the API with the service role: RLS on, no policies.

CREATE TABLE IF NOT EXISTS public.payment_requests (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan        text NOT NULL,
    amount_inr  integer NOT NULL,
    method      text NOT NULL DEFAULT 'upi',
    reference   text NOT NULL,
    status      text NOT NULL DEFAULT 'pending',
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_at  timestamptz,
    decided_by  text,
    CONSTRAINT payment_requests_plan_check   CHECK (plan IN ('pro', 'team')),
    CONSTRAINT payment_requests_amount_check CHECK (amount_inr > 0),
    CONSTRAINT payment_requests_status_check CHECK (status IN ('pending', 'approved', 'rejected'))
);

-- A transaction reference can be claimed once (a rejected claim frees it,
-- so a typo can be corrected), and an account has at most one claim waiting.
-- Enforced here, not only in the API, so two simultaneous submissions cannot
-- both get through.
CREATE UNIQUE INDEX IF NOT EXISTS payment_requests_reference_live
    ON public.payment_requests (reference) WHERE status <> 'rejected';
CREATE UNIQUE INDEX IF NOT EXISTS payment_requests_one_pending
    ON public.payment_requests (user_id) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_payment_requests_status_created
    ON public.payment_requests (status, created_at DESC);

ALTER TABLE public.payment_requests ENABLE ROW LEVEL SECURITY;
