-- HireLens — 005: saved job descriptions
--
-- A job description is written once and used against every shortlist for that
-- role. Storing it means the same text ranks every batch, instead of whatever
-- was pasted that morning.
--
-- Idempotent: safe to run more than once.

CREATE TABLE IF NOT EXISTS public.saved_jds (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL,
    name         text NOT NULL,
    jd_text      text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);

-- The picker lists a recruiter's own descriptions, newest edit first.
CREATE INDEX IF NOT EXISTS idx_saved_jds_user
    ON public.saved_jds (user_id, updated_at DESC);

-- One name per recruiter. Saving over "Senior Backend Engineer" replaces it,
-- rather than leaving two entries with the same label and no way to tell them
-- apart. Case-insensitive, because nobody remembers how they capitalised it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_jds_user_name
    ON public.saved_jds (user_id, lower(name));

-- Keep updated_at honest without the application having to remember.
CREATE OR REPLACE FUNCTION public.touch_saved_jd_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS saved_jds_touch_updated_at ON public.saved_jds;
CREATE TRIGGER saved_jds_touch_updated_at
    BEFORE UPDATE ON public.saved_jds
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_saved_jd_updated_at();

-- The API connects with the service-role key and filters on user_id itself.
-- RLS is the second line: it keeps the anon and authenticated keys safe if a
-- browser ever reads this table directly.
ALTER TABLE public.saved_jds ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'saved_jds'
          AND policyname = 'saved_jds_owner_all'
    ) THEN
        CREATE POLICY saved_jds_owner_all ON public.saved_jds
            FOR ALL
            USING (auth.uid() = user_id)
            WITH CHECK (auth.uid() = user_id);
    END IF;
END $$;
