-- HireLens — session revocation, and a foreign key that blocked user deletion.
--
-- Run after 001-007. Idempotent: safe to re-run.

-- ── 1. Revoking sessions ─────────────────────────────────────────────────────
--
-- The API's session tokens are valid for seven days and were not revocable:
-- a password reset left every existing session — including a stolen one —
-- working until it expired. A row here means "tokens for this user issued
-- before revoked_before are no longer accepted". Written on password reset
-- and on "sign out everywhere"; read (and cached briefly) on each request.
--
-- Server-only: RLS on, no policies, so neither anon nor authenticated can
-- read or write it. The API uses the service role.
CREATE TABLE IF NOT EXISTS public.session_revocations (
    user_id         uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    revoked_before  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.session_revocations ENABLE ROW LEVEL SECURITY;

-- ── 2. team_invites.invited_by ───────────────────────────────────────────────
--
-- This referenced auth.users with no ON DELETE action and NOT NULL, so
-- deleting any user who had ever sent a team invite failed with a foreign-key
-- error — including a data-deletion request handled from the Supabase
-- dashboard. The invite itself stays meaningful without its sender.
ALTER TABLE public.team_invites ALTER COLUMN invited_by DROP NOT NULL;
ALTER TABLE public.team_invites DROP CONSTRAINT IF EXISTS team_invites_invited_by_fkey;
ALTER TABLE public.team_invites
    ADD CONSTRAINT team_invites_invited_by_fkey
    FOREIGN KEY (invited_by) REFERENCES auth.users(id) ON DELETE SET NULL;
