-- HireLens — Core Schema
--
-- This file was missing. 002 adds a `team_id` column to public.reports and
-- foreign-keys four tables to it, so on a fresh project 002 failed on its
-- first statement and nothing after it ran either. Everything the app needs
-- now starts here.
--
-- Run these in order, in the Supabase SQL Editor:
--   001_core_schema.sql
--   002_team_collaboration.sql
--   003_candidate_notifications.sql
--
-- Every statement is idempotent, so running the set again on a project that
-- already has some of it is a no-op rather than an error.
--
-- A note on RLS. The backend talks to Postgres with the service-role key,
-- which bypasses row-level security entirely — so these policies are not what
-- keeps one recruiter's candidates away from another's. That is enforced in
-- application code (every query filters on user_id, and
-- app/services/teams/access.py gates shared reports). The policies are the
-- second line: they make the anon/authenticated keys safe if anything is ever
-- read from the browser directly.

-- ── Reports ─────────────────────────────────────────────────────────────────
-- One row per analysed CV. `report_data` holds the whole analysis blob; the
-- top-level columns are the ones the dashboard filters, sorts and exports on,
-- so they are indexed and the JSON is not.
CREATE TABLE IF NOT EXISTS public.reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_id UUID,
  file_name TEXT NOT NULL,
  candidate_name TEXT,
  overall_score INTEGER CHECK (overall_score >= 0 AND overall_score <= 100),
  recommendation TEXT CHECK (recommendation IN ('recommended', 'manual_review', 'high_risk')),
  report_data JSONB NOT NULL DEFAULT '{}'::JSONB,
  recruiter_decision TEXT CHECK (recruiter_decision IN ('advance', 'schedule_followup', 'reject')),
  decision_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- The dashboard always filters by owner and orders by one of these columns.
-- Without the composite indexes every page of every recruiter's list is a
-- sequential scan of the whole table, which on a nano instance is the
-- difference between a fast page and a visible wait.
CREATE INDEX IF NOT EXISTS idx_reports_user_id ON public.reports (user_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON public.reports (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_user_created ON public.reports (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_user_score ON public.reports (user_id, overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_reports_user_recommendation ON public.reports (user_id, recommendation);

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'reports' AND policyname = 'Users own their reports'
  ) THEN
    CREATE POLICY "Users own their reports" ON public.reports
      FOR ALL USING (auth.uid() = user_id);
  END IF;
END $$;

-- ── Profiles ────────────────────────────────────────────────────────────────
-- A readable name for a user id.
--
-- Comment threads, team rosters and the signature on candidate emails all
-- need to turn a user id into a person. Without Supabase those names come
-- from the local SQLite users table — but on a Supabase deployment the users
-- live in auth.users, which that table knows nothing about, so every
-- teammate showed as a neutral badge and every candidate email was signed
-- with the recruiter's raw email address. auth.users is not readable through
-- PostgREST, so the names are mirrored here.
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT,
  full_name TEXT,
  company TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Kept in step with auth.users automatically, so signing up is still one
-- call and a profile can never be forgotten.
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (id, email, full_name, company)
  VALUES (
    NEW.id,
    NEW.email,
    NULLIF(TRIM(COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', '')), ''),
    NULLIF(TRIM(COALESCE(NEW.raw_user_meta_data->>'company', '')), '')
  )
  ON CONFLICT (id) DO UPDATE
    SET email      = EXCLUDED.email,
        full_name  = COALESCE(EXCLUDED.full_name, public.profiles.full_name),
        company    = COALESCE(EXCLUDED.company, public.profiles.company),
        updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT OR UPDATE OF email, raw_user_meta_data ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Anyone who signed up before this file existed.
INSERT INTO public.profiles (id, email, full_name, company)
SELECT
  u.id,
  u.email,
  NULLIF(TRIM(COALESCE(u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name', '')), ''),
  NULLIF(TRIM(COALESCE(u.raw_user_meta_data->>'company', '')), '')
FROM auth.users u
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'Profiles are readable by signed-in users'
  ) THEN
    -- A name and an email address, to people who are already signed in.
    -- That is what a roster and a comment thread show anyway.
    CREATE POLICY "Profiles are readable by signed-in users" ON public.profiles
      FOR SELECT TO authenticated USING (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'You can edit your own profile'
  ) THEN
    CREATE POLICY "You can edit your own profile" ON public.profiles
      FOR UPDATE TO authenticated USING (auth.uid() = id) WITH CHECK (auth.uid() = id);
  END IF;
END $$;
