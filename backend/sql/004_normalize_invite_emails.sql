-- HireLens — 004: one spelling for an invited address
--
-- Invites are matched by email when the invitee signs up. The API lowercases
-- the address on the way in, but rows written before it did hold whatever the
-- inviter typed, and an address differing only in case matches nothing — the
-- invitee signs up, joins no team, and neither side sees an error.
--
-- This backfills the existing rows and installs a trigger so no client, old
-- or new, can write another spelling.
--
-- Idempotent: safe to run more than once.

-- ── Backfill ────────────────────────────────────────────────────────────────
-- Drop any duplicate that only differs by case first, keeping the oldest
-- pending invite for each address, so the unique work below cannot collide.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY team_id, lower(btrim(email)), status
               ORDER BY created_at NULLS LAST, id
           ) AS rn
    FROM public.team_invites
)
DELETE FROM public.team_invites t
USING ranked r
WHERE t.id = r.id AND r.rn > 1;

UPDATE public.team_invites
SET email = lower(btrim(email))
WHERE email IS DISTINCT FROM lower(btrim(email));

-- ── Trigger ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.normalize_team_invite_email()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    NEW.email := lower(btrim(NEW.email));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS team_invites_normalize_email ON public.team_invites;
CREATE TRIGGER team_invites_normalize_email
    BEFORE INSERT OR UPDATE OF email ON public.team_invites
    FOR EACH ROW
    EXECUTE FUNCTION public.normalize_team_invite_email();

-- Matching invites by address is the hot path at sign-up.
CREATE INDEX IF NOT EXISTS idx_team_invites_email_status
    ON public.team_invites (email, status);
