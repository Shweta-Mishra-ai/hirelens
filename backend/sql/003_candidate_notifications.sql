-- HireLens — Candidate Decision Notification Tracking (run once in Supabase SQL Editor)
-- Adds two nullable columns to the existing public.reports table so the app can
-- show "Candidate notified on <date>" and prevent accidental double-sends.
-- This does NOT change how recruiter_decision is saved — recording a decision
-- and notifying the candidate remain two independent actions.

ALTER TABLE public.reports
  ADD COLUMN IF NOT EXISTS candidate_notified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS candidate_notified_decision TEXT
    CHECK (candidate_notified_decision IN ('advance', 'schedule_followup', 'reject'));

CREATE INDEX IF NOT EXISTS idx_reports_candidate_notified_at
  ON public.reports (candidate_notified_at);
