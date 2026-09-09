-- HireLens — Core Reports Schema (run this FIRST, before 002 and 003, in the
-- Supabase SQL Editor)
--
-- This was a genuine gap: 002_team_collaboration.sql and
-- 003_candidate_notifications.sql both run `ALTER TABLE public.reports`,
-- but no migration in this repo ever CREATEs `public.reports` itself. On a
-- fresh Supabase project — like the one that was just connected — none of
-- 001/002/003 have run yet, so `public.reports` doesn't exist and every
-- report read/write will fail until this runs. The app's `/api/v1/health`
-- endpoint actually detects this correctly (it does a real
-- `select id limit 1` against this table, not just an env-var presence
-- check) and reports `storage_mode: "local_fallback"` with a `status:
-- "degraded"` until this table exists — check that endpoint after running
-- this to confirm.
--
-- Run in this order: 001 (this file) → 002 → 003.

CREATE TABLE IF NOT EXISTS public.reports (
  id TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_id TEXT,
  file_name TEXT NOT NULL,
  candidate_name TEXT NOT NULL DEFAULT 'Unknown',
  overall_score INTEGER NOT NULL DEFAULT 0,
  recommendation TEXT NOT NULL DEFAULT 'manual_review'
    CHECK (recommendation IN ('recommended', 'manual_review', 'high_risk')),
  -- Full analysis result (credibility breakdown, flags, skills, talent
  -- velocity, etc.) as a single JSON blob. Top-level columns above exist
  -- so list/sort/filter/search can be done in SQL without unpacking JSON
  -- on every request — see list_reports() in app/api/v1/endpoints/reports.py.
  report_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  recruiter_decision TEXT
    CHECK (recruiter_decision IN ('advance', 'schedule_followup', 'reject')),
  decision_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_user_id ON public.reports (user_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON public.reports (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_recommendation ON public.reports (recommendation);

-- RLS: defense-in-depth only. The app connects with the Supabase
-- service-role key server-side, which bypasses RLS entirely — application
-- code in app/api/v1/endpoints/reports.py (ownership checks, team-share
-- checks) is what actually enforces access. This policy matters only if
-- something ever queries this table with a user-scoped (anon/authenticated)
-- key instead of the service key.
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owners can view their own reports" ON public.reports
  FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Owners can insert their own reports" ON public.reports
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "Owners can update their own reports" ON public.reports
  FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY "Owners can delete their own reports" ON public.reports
  FOR DELETE USING (user_id = auth.uid());
