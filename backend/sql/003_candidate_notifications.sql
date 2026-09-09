-- HireLens — Candidate Decision Notification Tracking (run once in Supabase SQL Editor)
-- Adds two nullable columns to the existing public.reports table so the app can
-- show "Candidate notified on <date>" and prevent accidental double-sends.
-- This does NOT change how recruiter_decision is saved — recording a decision
-- and notifying the candidate remain two independent actions.

-- ── Precondition ──────────────────────────────────────────────────────────
-- Stop with a readable message if 001_initial_schema.sql has not been run.
-- Without this, running the migrations out of order fails somewhere in the
-- middle with a bare `relation "public.reports" does not exist`, which does
-- not say which file to run or that order matters at all — and by then some
-- of the statements above may already have been applied.
DO $$
BEGIN
  IF to_regclass('public.reports') IS NULL THEN
    RAISE EXCEPTION
      'public.reports does not exist. Run backend/sql/001_initial_schema.sql first, then 002, then 003.';
  END IF;
END
$$;

ALTER TABLE public.reports
  ADD COLUMN IF NOT EXISTS candidate_notified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS candidate_notified_decision TEXT
    CHECK (candidate_notified_decision IN ('advance', 'schedule_followup', 'reject'));

CREATE INDEX IF NOT EXISTS idx_reports_candidate_notified_at
  ON public.reports (candidate_notified_at);
