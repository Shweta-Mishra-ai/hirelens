-- HireLens — Team Collaboration Schema (run once in Supabase SQL Editor)
-- Adds: teams, team membership, invites, per-report comments, per-report votes,
-- and a nullable team_id on reports so a report can be shared with a team
-- without changing who owns it (recruiter who ran the analysis keeps ownership).

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

CREATE TABLE IF NOT EXISTS public.teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.team_members (
  team_id UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  joined_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (team_id, user_id)
);

-- Invites are email-based, not user-id-based, because the invited person may
-- not have a HireLens account yet. Auto-accepted on their next login/signup
-- with a matching email (see app/api/v1/endpoints/auth.py) — no email
-- sending infrastructure required for a working v1.
CREATE TABLE IF NOT EXISTS public.team_invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  invited_by UUID NOT NULL REFERENCES auth.users(id),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'revoked')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.report_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID NOT NULL REFERENCES public.reports(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  comment TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- One vote per (report, user) — casting again updates the existing vote
-- rather than adding a duplicate, so the tally always reflects current opinions.
CREATE TABLE IF NOT EXISTS public.report_votes (
  report_id UUID NOT NULL REFERENCES public.reports(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  vote TEXT NOT NULL CHECK (vote IN ('advance', 'reject', 'maybe')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (report_id, user_id)
);

ALTER TABLE public.reports ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES public.teams(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_team_members_user ON public.team_members(user_id);
CREATE INDEX IF NOT EXISTS idx_team_invites_email ON public.team_invites(email) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_report_comments_report ON public.report_comments(report_id);
CREATE INDEX IF NOT EXISTS idx_report_votes_report ON public.report_votes(report_id);
CREATE INDEX IF NOT EXISTS idx_reports_team ON public.reports(team_id) WHERE team_id IS NOT NULL;

-- RLS: a report is visible to its owner OR any member of the team it's shared with.
ALTER TABLE public.teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.team_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_votes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Team members can view their teams" ON public.teams FOR SELECT
  USING (owner_id = auth.uid() OR id IN (SELECT team_id FROM public.team_members WHERE user_id = auth.uid()));

CREATE POLICY "Team members can view membership" ON public.team_members FOR SELECT
  USING (team_id IN (SELECT team_id FROM public.team_members WHERE user_id = auth.uid()));

CREATE POLICY "Team members can view/add comments on accessible reports" ON public.report_comments FOR ALL
  USING (
    report_id IN (
      SELECT id FROM public.reports
      WHERE user_id = auth.uid()
         OR team_id IN (SELECT team_id FROM public.team_members WHERE user_id = auth.uid())
    )
  );

CREATE POLICY "Team members can view/cast votes on accessible reports" ON public.report_votes FOR ALL
  USING (
    report_id IN (
      SELECT id FROM public.reports
      WHERE user_id = auth.uid()
         OR team_id IN (SELECT team_id FROM public.team_members WHERE user_id = auth.uid())
    )
  );

-- Note: the app also enforces access checks in application code
-- (app/services/teams/access.py) as defense-in-depth — don't rely on RLS alone
-- if you're using the Supabase service-role key server-side, which bypasses RLS.
