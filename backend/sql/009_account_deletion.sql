-- HireLens — self-serve account deletion.
--
-- Run after 001-008. Idempotent: safe to re-run.

-- ── Deleted accounts ─────────────────────────────────────────────────────────
--
-- Session tokens are valid for seven days, and the row that revokes them
-- (session_revocations) is removed with the user by its foreign key. Without
-- something that outlives the account, a deleted account's open sessions
-- would keep working until they expired. A row here refuses every token for
-- that user id.
--
-- It holds only the account's random id and when it was deleted — no email,
-- no name. Deliberately no foreign key: it must survive the user it refers to.
-- Server-only: RLS on, no policies; the API uses the service role.
CREATE TABLE IF NOT EXISTS public.deleted_accounts (
    user_id     uuid PRIMARY KEY,
    deleted_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.deleted_accounts ENABLE ROW LEVEL SECURITY;
